import base64
import io

from fastapi.testclient import TestClient
import pytest

from proofgrade.image_pages import rgb_png
from test_teacher import ASSIGNMENT, HEADERS, PASSWORD, teacher


def image_body(**changes):
    return {"student_code": "photo-01", "width": 2, "height": 1,
            "pixels_base64": base64.b64encode(b"\xff\x00\x00\x00\xff\x00").decode(), **changes}


def test_png_pixels_round_trip_through_independent_decoder():
    Image = pytest.importorskip("PIL.Image", reason="Independent decoder is in the optional media extra")
    # Distinct rows/channels expose stride, filter, orientation and color errors.
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 127, 64, 12])
    png = rgb_png(2, 2, base64.b64encode(pixels).decode())
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        assert image.size == (2, 2) and image.mode == "RGB"
        assert image.tobytes() == pixels
        assert image.info == {}


def test_browser_upload_is_private_and_deletion_removes_source(teacher):
    client, store, app = teacher
    assignment = client.post("/api/teacher/assignments", json=ASSIGNMENT).json()
    url = f"/api/teacher/assignments/{assignment['id']}/image-uploads"
    response = client.post(url, json=image_body())
    assert response.status_code == 201, response.text
    submission = response.json()
    assert submission["status"] == "transcription_draft" and submission["page_count"] == 1
    path = f"/api/teacher/submissions/{submission['id']}"
    page = client.get(path + "/pages/1")
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["content-type"] == "image/png"
    with TestClient(app, headers=HEADERS) as other:
        assert other.post(url, json=image_body()).status_code == 401
        other.post("/api/teacher/login", json={"username": "other", "password": PASSWORD})
        assert other.get(path + "/pages/1").status_code == 404
        # Ownership is checked before pixel decoding, even with a malformed payload.
        assert other.post(url, json=image_body(pixels_base64="????")).status_code == 404
    assert client.post(url, json=image_body()).status_code == 409
    assert client.delete(path).status_code == 200
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone()[0] == 0


def test_rejects_invalid_pixels_without_creating_partial_records(teacher):
    client, store, _ = teacher
    assignment = client.post("/api/teacher/assignments", json=ASSIGNMENT).json()
    url = f"/api/teacher/assignments/{assignment['id']}/image-uploads"
    invalid = [
        {"width": 0}, {"width": True}, {"width": "2"}, {"height": 1.0}, {"height": 2401},
        {"width": 2400, "height": 2400}, {"pixels_base64": ""},
        {"pixels_base64": "AAAA"}, {"pixels_base64": "!!!!!!!!"},
        {"pixels_base64": "AAAAAA=="}, {"pixels_base64": "é" * 8},
        {"pixels_base64": "A" * 12_000_004}, {"file_base64": "not accepted"},
    ]
    for changes in invalid:
        response = client.post(url, json=image_body(**changes))
        assert response.status_code in (400, 422), (changes.keys(), response.text[:300])
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM submissions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM pages").fetchone()[0] == 0


def test_image_body_limit_includes_chunked_requests_and_allows_large_valid_photo(teacher):
    client, _, _ = teacher
    assignment = client.post("/api/teacher/assignments", json=ASSIGNMENT).json()
    url = f"/api/teacher/assignments/{assignment['id']}/image-uploads"
    response = client.post(url, content=(b" " * 1024 * 1024 for _ in range(13)),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    # Maximum prepared size remains within the JSON cap, beyond the ordinary 256 KiB limit.
    response = client.post(url, json=image_body(width=2000, height=1500,
                           pixels_base64=base64.b64encode(b"\xff" * 9_000_000).decode()))
    assert response.status_code == 201, response.text[:300]
