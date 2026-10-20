import pytest
from fastapi.testclient import TestClient

from proofgrade.api import create_app
from proofgrade.providers import DemoProvider, DisabledProvider


@pytest.fixture
def client():
    with TestClient(create_app(DemoProvider())) as instance:
        yield instance


def test_problem_list_never_exposes_answer_key(client):
    problems = client.get("/api/problems").json()
    assert len(problems) >= 6
    assert all(set(problem) == {"id", "title", "equation", "topic"} for problem in problems)


def test_example_mistake_and_revision(client):
    response = client.post("/api/check", json={"problem_id": "linear-distribution", "steps": ["2x+3=10", "2x=7"]})
    assert response.status_code == 200
    result = response.json()
    assert result["first_error_step"] == 1 and result["hint_status"] == "verified"
    assert result["provider_mode"] == "demo"
    assert "correction" not in result and "final_solution" not in result
    revised = client.post("/api/check", json={"problem_id": "linear-distribution", "steps": ["2x+6=10", "2x=4", "x=2"]}).json()
    assert revised["status"] == "correct" and revised["hint"] is None


@pytest.mark.parametrize("steps", [[], [""], [" "], [1], ["x=2"] * 21, ["x=" + "2" * 256]])
def test_invalid_request_is_rejected(client, steps):
    assert client.post("/api/check", json={"problem_id": "linear-distribution", "steps": steps}).status_code == 422


def test_unknown_problem_and_caller_cannot_supply_answer_key(client):
    assert client.post("/api/check", json={"problem_id": "unknown", "steps": ["x=2"]}).status_code == 404
    assert client.post("/api/check", json={"problem_id": "linear-distribution", "steps": ["x=2"], "answer": "x=2"}).status_code == 422


def test_correct_incomplete_and_unsupported_are_distinct(client):
    for steps, expected in [(["2x=4"], "incomplete"), (["x=2"], "correct"), (["1/x=2"], "unsupported")]:
        result = client.post("/api/check", json={"problem_id": "linear-distribution", "steps": steps}).json()
        assert result["status"] == expected


def test_disabled_provider_preserves_checker():
    with TestClient(create_app(DisabledProvider())) as client:
        result = client.post("/api/check", json={"problem_id": "linear-distribution", "steps": ["x=3"]}).json()
        assert result["status"] == "incorrect"
        assert result["hint_status"] == "unavailable" and result["hint"] is None


def test_frontend_assets_and_config(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/config").json()["provider_mode"] == "demo"
    page = client.get("/practice")
    assert page.status_code == 200 and "Check my work" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert "Teacher workspace" in client.get("/").text
