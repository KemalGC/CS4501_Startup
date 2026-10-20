import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("blocked", ["PIL", "pypdfium2"])
def test_cold_start_and_typed_grading_with_blocked_native_library(tmp_path, blocked):
    # A fresh interpreter detects eager imports even when other tests loaded Pillow.
    script = textwrap.dedent('''
        import base64
        import builtins
        import os

        original_import = builtins.__import__
        blocked = os.environ["PROOFGRADE_TEST_BLOCKED_LIBRARY"]
        def controlled_import(name, *args, **kwargs):
            if name == blocked or name.startswith(blocked + "."):
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
            assert capabilities["images"] == (blocked != "PIL")
            assert capabilities["pdf"] is False
            assert "typed student work" in capabilities["message"]
            assignment = client.post("/api/teacher/assignments", json={
                "title": "Typed fallback", "class_name": "Test class", "questions": [{
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
            raw = b"%PDF-test" if blocked == "pypdfium2" else b"unavailable image"
            failed = client.post("/api/teacher/assignments/" + assignment["id"] + "/uploads", json={
                "student_code": "scan-01", "file_base64": base64.b64encode(raw).decode()})
            assert failed.status_code == 503, failed.text
            assert "typed student work" in failed.json()["detail"]
            assert len(client.get(submissions).json()) == 1
            assert client.get("/health").status_code == 200
    ''')
    environment = dict(os.environ, PROOFGRADE_TEACHER_DB=str(tmp_path / "teachers.sqlite3"),
                       PROOFGRADE_TEST_BLOCKED_LIBRARY=blocked, PROOFGRADE_HINT_MODE="demo",
                       PROOFGRADE_TEACHER_AI="disabled", PROOFGRADE_STORE_ATTEMPTS="false")
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
