import base64
import io
import json

from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pypdfium2 as pdfium
import pytest

from proofgrade.api import create_app
from proofgrade.feedback import ProviderUnavailable
from proofgrade.providers import DemoProvider
from proofgrade.teacher_ai import OpenAITeacherModel
from proofgrade.teacher_uploads import render_upload
from test_teacher import ASSIGNMENT, HEADERS, PASSWORD, approval, create_work, teacher


def png_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(stream, format="PNG")
    return stream.getvalue()


def encoded(raw=None):
    return base64.b64encode(raw if raw is not None else png_bytes()).decode()


def answers():
    return [{"question_id": "Q1", "steps": ["x+3=5", "x=2"], "source_page": 1, "unreadable": False, "note": ""},
            {"question_id": "Q2", "steps": ["x=-3 or x=3"], "source_page": 1, "unreadable": False, "note": ""}]


def model_response(content):
    return httpx.Response(200, json={"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(content)}]}]})


def test_uploaded_pages_are_private_and_deleted(teacher):
    client, store, app = teacher
    assignment, _ = create_work(client)
    upload = client.post(f"/api/teacher/assignments/{assignment['id']}/uploads",
                         json={"student_code": "scan-01", "file_base64": encoded()})
    assert upload.status_code == 201, upload.text
    submission = upload.json()
    path = f"/api/teacher/submissions/{submission['id']}/pages/1"
    page = client.get(path)
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    assert page.headers["cache-control"] == "no-store"
    with TestClient(app, headers=HEADERS) as other:
        assert other.get(path).status_code == 401
        other.post("/api/teacher/login", json={"username": "other", "password": PASSWORD})
        assert other.get(path).status_code == 404
    assert client.post(f"/api/teacher/submissions/{submission['id']}/extract", json={"revision": 1}).status_code == 503
    assert client.delete(f"/api/teacher/submissions/{submission['id']}").status_code == 200
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone()[0] == 0


def test_pdf_render_and_page_limit(monkeypatch):
    monkeypatch.setenv("PROOFGRADE_PDF_UPLOADS", "true")
    def pdf_bytes(count):
        document = pdfium.PdfDocument.new()
        for _ in range(count):
            page = document.new_page(300, 400)
            page.close()
        stream = io.BytesIO()
        document.save(stream)
        document.close()
        return stream.getvalue()
    assert len(render_upload(encoded(pdf_bytes(2)))) == 2
    with pytest.raises(ValueError, match="1–5"):
        render_upload(encoded(pdf_bytes(6)))
    for raw in [b"<svg onload='alert(1)'></svg>", b"not an image", b"%PDF-broken"]:
        with pytest.raises(ValueError):
            render_upload(encoded(raw))


def test_oversized_image_and_bad_base64():
    stream = io.BytesIO()
    Image.new("1", (5000, 5000)).save(stream, format="PNG")
    with pytest.raises(ValueError, match="20 megapixels"):
        render_upload(encoded(stream.getvalue()))
    with pytest.raises(ValueError):
        render_upload("not_base64!")


def test_chunked_request_size_cap(teacher):
    client, _, _ = teacher
    response = client.post("/api/teacher/login", content=iter([b"x" * 200000, b"x" * 200000]),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_vision_retry_preserves_data_and_omits_answer_key():
    requests = []
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        candidate = answers()
        if len(requests) == 1:
            candidate[0]["question_id"] = "invented"
        return model_response({"answers": candidate})
    model = OpenAITeacherModel("test-key", "vision-test", httpx.Client(transport=httpx.MockTransport(handler)))
    result = model.extract(ASSIGNMENT, [png_bytes()])
    assert result["attempts"] == 2
    assert result["answers"][0]["steps"] == ["x+3=5", "x=2"]
    assert requests[0]["store"] is False
    prompt = requests[0]["input"][0]["content"][0]["text"]
    assert '"answer"' not in prompt and "rubric" not in prompt
    assert any(c["type"] == "input_image" for c in requests[0]["input"][0]["content"])
    assert "validation_failures" in requests[1]["input"][0]["content"][-1]["text"]


def test_vision_invalid_page_withheld_after_three_attempts():
    calls = []
    def handler(request):
        calls.append(1)
        candidate = answers()
        candidate[0]["source_page"] = 5
        return model_response({"answers": candidate})
    model = OpenAITeacherModel("test", "vision-test", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable, match="Three"):
        model.extract(ASSIGNMENT, [png_bytes()])
    assert len(calls) == 3


def test_refusal_never_becomes_transcription():
    def handler(request):
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]})
    model = OpenAITeacherModel("test", "vision-test", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable):
        model.extract(ASSIGNMENT, [png_bytes()])


def test_model_practice_retries_wrong_answer_and_checks_skill():
    calls = []
    def handler(request):
        calls.append(1)
        return model_response({"questions": [
            {"equation": "2(x+3)=10", "answer": "x=3" if len(calls) == 1 else "x=2"},
            {"equation": "3(x+2)=15", "answer": "x=3"}, {"equation": "4(x+1)=20", "answer": "x=4"}]})
    model = OpenAITeacherModel("test", "vision-test", httpx.Client(transport=httpx.MockTransport(handler)))
    result = model.practice("distribution")
    assert result["source"] == "openai_checked" and result["attempts"] == 2
    assert result["questions"][0]["answer"] == "x=2"


def test_extract_invalidates_old_grade_and_requires_confirmation(teacher):
    _, store, _ = teacher
    class MockVision:
        def extract(self, assignment, pages):
            return {"answers": answers(), "attempts": 1}
    with TestClient(create_app(DemoProvider(), teacher_store=store, teacher_model=MockVision()), headers=HEADERS) as client:
        client.post("/api/teacher/login", json={"username": "teacher", "password": PASSWORD})
        assignment, _ = create_work(client)
        submission = client.post(f"/api/teacher/assignments/{assignment['id']}/uploads",
            json={"student_code": "scan", "file_base64": encoded()}).json()
        sid = submission["id"]
        draft = client.post(f"/api/teacher/submissions/{sid}/transcript",
                            json={"revision": 1, "confirmed": True, "answers": answers()}).json()
        approved = client.post(f"/api/teacher/submissions/{sid}/approve", json=approval(draft)).json()
        extracted = client.post(f"/api/teacher/submissions/{sid}/extract", json={"revision": approved["revision"]})
        assert extracted.status_code == 200, extracted.text
        assert extracted.json()["status"] == "transcription_draft"
        assert extracted.json()["results"] == []
        assert "approved_at" not in extracted.json()
        assert client.get(f"/api/teacher/assignments/{assignment['id']}/analytics").json()["approved"] == 0
        assert client.post(f"/api/teacher/submissions/{sid}/approve", json=approval(draft)).status_code == 409
