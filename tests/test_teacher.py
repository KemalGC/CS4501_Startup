import copy

from fastapi.testclient import TestClient
import pytest

from proofgrade.api import create_app
from proofgrade.providers import DemoProvider
from proofgrade.teacher_store import TeacherStore

PASSWORD = "test-password-not-for-deployment"
HEADERS = {"X-ProofGrade-Request": "1"}
ASSIGNMENT = {
    "title": "Algebra checkpoint", "class_name": "Algebra 1",
    "questions": [
        {"id": "Q1", "equation": "2(x+3)=10", "answer": "x=2", "skill": "distribution",
         "criteria": [{"id": "answer", "label": "Complete final answer", "kind": "final_answer", "points": 3},
                      {"id": "work", "label": "Valid intermediate work", "kind": "valid_work", "points": 2}]},
        {"id": "Q2", "equation": "x^2=9", "answer": "x=-3 or x=3", "skill": "quadratic",
         "criteria": [{"id": "answer", "label": "Complete final answer", "kind": "final_answer", "points": 5}]}
    ]
}


@pytest.fixture
def teacher(tmp_path):
    store = TeacherStore(tmp_path / "teachers.sqlite3")
    store.create_teacher("teacher", PASSWORD)
    store.create_teacher("other", PASSWORD)
    app = create_app(DemoProvider(), teacher_store=store)
    with TestClient(app, headers=HEADERS) as client:
        assert client.post("/api/teacher/login", json={"username": "teacher", "password": PASSWORD}).status_code == 200
        yield client, store, app


def create_work(client):
    response = client.post("/api/teacher/assignments", json=ASSIGNMENT)
    assert response.status_code == 201, response.text
    assignment = response.json()
    response = client.post(f"/api/teacher/assignments/{assignment['id']}/submissions", json={"student_code": "student-01"})
    assert response.status_code == 201, response.text
    return assignment, response.json()


def transcript(client, submission, steps=None):
    answers = [{"question_id": "Q1", "steps": steps or ["2x+3=10", "2x=7"], "source_page": None, "unreadable": False, "note": ""},
               {"question_id": "Q2", "steps": ["x=-3 or x=3"], "source_page": None, "unreadable": False, "note": ""}]
    return client.post(f"/api/teacher/submissions/{submission['id']}/transcript",
                       json={"revision": submission["revision"], "confirmed": True, "answers": answers})


def approval(draft):
    return {"revision": draft["revision"], "confirmed": True, "questions": [
        {"question_id": r["question_id"], "scores": [{"criterion_id": c["id"], "points": c["suggested"]}
                                                   for c in r["criteria"]],
         "category": r["category"], "feedback": r["feedback"], "reason": ""}
        for r in draft["results"]]}


def test_teacher_end_to_end_grade_gap_practice_export(teacher):
    client, _, _ = teacher
    assignment, submission = create_work(client)
    aid, sid = assignment["id"], submission["id"]
    assert client.get(f"/api/teacher/assignments/{aid}/analytics").json()["approved"] == 0
    response = transcript(client, submission)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["results"][0]["category"] == "distribution"
    assert draft["results"][0]["check"]["first_error_step"] == 1
    assert draft["results"][1]["criteria"][0]["suggested"] == 5
    assert client.get(f"/api/teacher/submissions/{sid}/feedback.txt").status_code == 409
    reviewed = client.post(f"/api/teacher/submissions/{sid}/approve", json=approval(draft))
    assert reviewed.status_code == 200, reviewed.text
    summary = client.get(f"/api/teacher/assignments/{aid}/analytics").json()
    assert (summary["approved"], summary["unresolved"]) == (1, 0)
    assert summary["students"][0]["earned"] == 5
    assert summary["gaps"] == [{"skill": "distribution", "responses": 1}]
    assert "student-01,5,10,50.0" in client.get(f"/api/teacher/assignments/{aid}/grades.csv").text
    practice = client.post(f"/api/teacher/assignments/{aid}/practice", json={"skill": "distribution"}).json()
    pid = practice["id"]
    assert client.get(f"/api/teacher/practice/{pid}/questions.txt").status_code == 409
    assert client.post(f"/api/teacher/practice/{pid}/approve").status_code == 200
    exported = client.get(f"/api/teacher/practice/{pid}/questions.txt").text
    assert "answer" not in exported.lower() and all(q["equation"] in exported for q in practice["questions"])
    assert client.post(f"/api/teacher/assignments/{aid}/practice", json={"skill": "linear"}).status_code == 409


def test_private_records_and_logout(teacher):
    client, _, app = teacher
    assignment, submission = create_work(client)
    with TestClient(app, headers=HEADERS) as other:
        assert other.get("/api/teacher/assignments").status_code == 401
        other.post("/api/teacher/login", json={"username": "other", "password": PASSWORD})
        assert other.get("/api/teacher/assignments").json() == []
        assert other.get(f"/api/teacher/assignments/{assignment['id']}").status_code == 404
        assert other.get(f"/api/teacher/submissions/{submission['id']}").status_code == 404
        assert other.delete(f"/api/teacher/submissions/{submission['id']}").status_code == 404
    assert client.post("/api/teacher/logout").status_code == 200
    assert client.get("/api/teacher/assignments").status_code == 401


def test_revised_transcript_invalidates_approval_and_stale_writes(teacher):
    client, _, _ = teacher
    assignment, submission = create_work(client)
    draft = transcript(client, submission).json()
    approved = client.post(f"/api/teacher/submissions/{submission['id']}/approve", json=approval(draft)).json()
    revised = transcript(client, approved, ["2x+6=10", "2x=4", "x=2"])
    assert revised.status_code == 200
    assert revised.json()["status"] == "grading_draft"
    assert "approved_at" not in revised.json()
    assert client.get(f"/api/teacher/assignments/{assignment['id']}/analytics").json()["approved"] == 0
    assert transcript(client, approved).status_code == 409
    assert len(client.get(f"/api/teacher/submissions/{submission['id']}/history").json()) == 3


def test_override_requires_reason_and_bounds(teacher):
    client, _, _ = teacher
    _, submission = create_work(client)
    draft = transcript(client, submission).json()
    body = approval(draft)
    body["questions"][0]["scores"][0]["points"] = 1
    url = f"/api/teacher/submissions/{submission['id']}/approve"
    assert client.post(url, json=body).status_code == 400
    body["questions"][0]["reason"] = "Partial credit awarded after checking the original work."
    body["questions"][0]["scores"][0]["points"] = 4
    assert client.post(url, json=body).status_code == 400
    body["questions"][0]["scores"][0]["points"] = 1
    assert client.post(url, json=body).json()["results"][0]["earned"] == 1


@pytest.mark.parametrize("answer", ["x=3", "x^2=9", "1/x=2"])
def test_invalid_teacher_keys_are_rejected(teacher, answer):
    client, _, _ = teacher
    body = copy.deepcopy(ASSIGNMENT)
    body["questions"][1]["answer"] = answer
    assert client.post("/api/teacher/assignments", json=body).status_code == 422


def test_missing_transcription_questions_and_invented_pages_rejected(teacher):
    client, _, _ = teacher
    _, submission = create_work(client)
    body = {"revision": 1, "confirmed": True, "answers": [submission["answers"][0]]}
    url = f"/api/teacher/submissions/{submission['id']}/transcript"
    assert client.post(url, json=body).status_code == 400
    body["answers"] = submission["answers"]
    body["answers"][0]["source_page"] = 1
    assert client.post(url, json=body).status_code == 400


def test_unsupported_work_and_manual_criteria_need_explicit_scores(teacher):
    client, _, _ = teacher
    _, submission = create_work(client)
    draft = transcript(client, submission, ["1/x=2"]).json()
    assert all(c["suggested"] is None for c in draft["results"][0]["criteria"])
    body = approval(draft)
    assert client.post(f"/api/teacher/submissions/{submission['id']}/approve", json=body).status_code == 422
    for criterion in body["questions"][0]["scores"]:
        criterion["points"] = 0
    body["questions"][0]["reason"] = "Teacher reviewed the unsupported notation manually."
    assert client.post(f"/api/teacher/submissions/{submission['id']}/approve", json=body).status_code == 200


def test_csrf_and_cross_origin_rejected(teacher):
    client, _, app = teacher
    with TestClient(app) as unauth:
        assert unauth.post("/api/teacher/login", json={"username": "teacher", "password": PASSWORD}).status_code == 403
    assert client.post("/api/teacher/assignments", json=ASSIGNMENT, headers={"Origin": "https://other.example"}).status_code == 403


def test_delete_cascades_records(teacher):
    client, store, _ = teacher
    assignment, submission = create_work(client)
    transcript(client, submission)
    assert client.delete(f"/api/teacher/assignments/{assignment['id']}").status_code == 200
    assert client.get(f"/api/teacher/submissions/{submission['id']}").status_code == 404
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM review_events").fetchone()[0] == 0


def test_duplicate_codes_and_unknown_scores_rejected(teacher):
    client, _, _ = teacher
    assignment, submission = create_work(client)
    assert client.post(f"/api/teacher/assignments/{assignment['id']}/submissions",
                       json={"student_code": "student-01"}).status_code == 409
    draft = transcript(client, submission).json()
    body = approval(draft)
    body["questions"][0]["scores"][0]["criterion_id"] = "invented"
    assert client.post(f"/api/teacher/submissions/{submission['id']}/approve", json=body).status_code == 400


def test_alternative_valid_method_receives_credit(teacher):
    client, _, _ = teacher
    _, submission = create_work(client)
    draft = transcript(client, submission, ["x+3=5", "x=2"]).json()
    assert [c["suggested"] for c in draft["results"][0]["criteria"]] == [3, 2]


def test_unsupported_later_line_does_not_crash_or_get_zero(teacher):
    client, _, _ = teacher
    _, submission = create_work(client)
    response = transcript(client, submission, ["2x+3=10", "x=7/2", "some handwritten explanation"])
    assert response.status_code == 200
    assert response.json()["results"][0]["needs_review"]
    assert response.json()["results"][0]["criteria"][0]["suggested"] is None
