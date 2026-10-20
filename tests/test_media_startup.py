import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("blocked", ["PIL", "pypdfium2", "PIL,pypdfium2"])
def test_cold_start_image_upload_and_grading_with_blocked_native_libraries(tmp_path, blocked):
    # A fresh interpreter detects eager imports even when other tests loaded Pillow.
    script = textwrap.dedent('''
        import base64
        import builtins
        import os

        original_import = builtins.__import__
        blocked = os.environ["PROOFGRADE_TEST_BLOCKED_LIBRARY"].split(",")
        attempted = []
        def controlled_import(name, *args, **kwargs):
            if name.split(".")[0] in ("PIL", "pypdfium2"):
                attempted.append(name)
            if any(name == library or name.startswith(library + ".") for library in blocked):
                raise ImportError("DLL load failed: An Application Control policy has blocked this file.")
            return original_import(name, *args, **kwargs)
        builtins.__import__ = controlled_import

        from fastapi.testclient import TestClient
        from proofgrade.api import create_app
        from proofgrade.teacher_store import TeacherStore

        store = TeacherStore(os.environ["PROOFGRADE_TEACHER_DB"])
        store.create_teacher("teacher", "synthetic-test-password")
        with TestClient(create_app(teacher_store=store), headers={"X-ProofGrade-Request": "1"}) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/teacher").status_code == 200
            assert client.post("/api/check", json={"problem_id": "linear-distribution", "steps": ["x=2"]}).json()["status"] == "correct"
            assert client.post("/api/teacher/login", json={"username": "teacher", "password": "synthetic-test-password"}).status_code == 200
            capabilities = client.get("/api/teacher/session").json()["uploads"]
            assert capabilities["images"] is True
            assert capabilities["image_transport"] == "browser_rgb"
            assert capabilities["pdf"] is False
            assert attempted == [], attempted
            assignment = client.post("/api/teacher/assignments", json={
                "title": "Photos without native libraries", "class_name": "Test class", "questions": [{
                    "id": "Q1", "equation": "2x=4", "answer": "x=2", "skill": "linear",
                    "criteria": [{"id": "answer", "label": "Final answer", "kind": "final_answer", "points": 3}]}]
            }).json()
            submissions = "/api/teacher/assignments/" + assignment["id"] + "/submissions"
            submission = client.post(submissions, json={"student_code": "typed-01"}).json()
            path = "/api/teacher/submissions/" + submission["id"]
            draft = client.post(path + "/transcript", json={"revision": 1, "confirmed": True, "answers": [{
                "question_id": "Q1", "steps": ["x=2"], "source_page": None, "unreadable": False, "note": ""}]}).json()
            result = draft["results"][0]
            approved = client.post(path + "/approve", json={"revision": draft["revision"], "confirmed": True, "questions": [{
                "question_id": "Q1", "scores": [{"criterion_id": "answer", "points": 3}],
                "category": result["category"], "feedback": result["feedback"], "reason": ""}]})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            image = client.post("/api/teacher/assignments/" + assignment["id"] + "/image-uploads", json={
                "student_code": "photo-01", "width": 100, "height": 200,
                "pixels_base64": base64.b64encode(b"\\xff" * 60_000).decode()})
            assert image.status_code == 201, image.text
            photo_path = "/api/teacher/submissions/" + image.json()["id"]
            page = client.get(photo_path + "/pages/1")
            assert page.status_code == 200 and page.content.startswith(b"\\x89PNG")
            draft = client.post(photo_path + "/transcript", json={"revision": 1, "confirmed": True, "answers": [{
                "question_id": "Q1", "steps": ["x=2"], "source_page": 1, "unreadable": False, "note": ""}]}).json()
            assert draft["status"] == "grading_draft"
            assert draft["results"][0]["criteria"][0]["suggested"] == 3
            assert attempted == [], attempted
            # Explicitly opting into PDFs cannot break the browser image path.
            os.environ["PROOFGRADE_PDF_UPLOADS"] = "true"
            capabilities = client.get("/api/teacher/session").json()["uploads"]
            assert capabilities["images"] is True and capabilities["pdf"] is False
            failed = client.post("/api/teacher/assignments/" + assignment["id"] + "/uploads", json={
                "student_code": "scan-01", "file_base64": base64.b64encode(b"%PDF-test").decode()})
            assert failed.status_code == 503, failed.text
            assert "typed student work" in failed.json()["detail"]
            assert len(client.get(submissions).json()) == 2
            assert client.get("/health").status_code == 200
    ''')
    environment = dict(os.environ, PROOFGRADE_TEACHER_DB=str(tmp_path / "teachers.sqlite3"),
                       PROOFGRADE_TEST_BLOCKED_LIBRARY=blocked, PROOFGRADE_HINT_MODE="demo",
                       PROOFGRADE_TEACHER_AI="disabled", PROOFGRADE_STORE_ATTEMPTS="false",
                       PROOFGRADE_PDF_UPLOADS="false")
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
