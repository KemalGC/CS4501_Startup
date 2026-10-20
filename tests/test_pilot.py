import sqlite3

from fastapi.testclient import TestClient
import pytest

from proofgrade.algebra import parse_statement
from proofgrade.api import create_app
from proofgrade.evaluate import evaluate
from proofgrade.metrics import summarize
from proofgrade.problems import PROBLEMS
from proofgrade.providers import DemoProvider
from proofgrade.storage import AttemptStore


@pytest.fixture
def pilot(tmp_path):
    path = tmp_path / "attempts.sqlite3"
    store = AttemptStore(path)
    with TestClient(create_app(DemoProvider(), store)) as client:
        yield client, path


def submit(client, steps, consent=True, previous=None, problem="linear-distribution"):
    return client.post("/api/check", json={"problem_id": problem, "steps": steps,
                       "consent": consent, "previous_attempt_id": previous})


def test_practice_keys_and_separate_evaluation_problems():
    assert len(PROBLEMS) == 30
    assert len({problem.id for problem in PROBLEMS}) == 30
    for problem in PROBLEMS:
        answer = parse_statement(problem.answer)
        assert answer.complete
        assert answer.solutions == parse_statement(problem.equation).solutions
        assert problem.review_status == "pending"
    result = evaluate("all")
    assert result["cases"] == 42 and result["failures"] == []
    assert result["instructor_reviewed_cases"] == 0


def test_storage_requires_both_enablement_and_consent(pilot):
    client, path = pilot
    assert client.get("/api/config").json()["collection_enabled"]
    assert submit(client, ["x=3"], consent=False).json()["attempt_id"] is None
    assert summarize(path, "demo")["stored_attempts"] == 0
    with TestClient(create_app(DemoProvider())) as disabled:
        assert submit(disabled, ["x=3"], consent=True).json()["attempt_id"] is None


def test_revision_metrics_and_rating_without_storing_equations(pilot):
    client, path = pilot
    first = submit(client, ["2x+3=10"]).json()
    assert first["hint_status"] == "verified"
    assert client.post(f"/api/attempts/{first['attempt_id']}/rating", json={"rating": 5}).status_code == 200
    revised = submit(client, ["2x+6=10", "2x=4", "x=2"], previous=first["attempt_id"]).json()
    assert revised["status"] == "correct"
    metrics = summarize(path, "demo")
    assert metrics["correction_rate"] == 1 and metrics["usefulness_4_or_5_rate"] == 1
    assert summarize(path, "openai")["stored_attempts"] == 0
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
    assert not columns.intersection({"steps", "email", "name", "equations", "hint", "api_key"})


def test_shortening_solution_is_not_counted_as_correction(pilot):
    client, path = pilot
    first = submit(client, ["2x+6=10", "2x=16"]).json()
    assert first["first_error_step"] == 2 and first["hint_status"] == "verified"
    submit(client, ["2x+6=10"], previous=first["attempt_id"])
    assert summarize(path, "demo")["corrected_after_first_hint"] == 0


def test_replays_do_not_double_count_and_no_revision_stays_in_denominator(pilot):
    client, path = pilot
    first = submit(client, ["2x+3=10"]).json()
    submit(client, ["x=2"], previous=first["attempt_id"])
    submit(client, ["x=2"], previous=first["attempt_id"])
    submit(client, ["2x+3=10"])
    metrics = summarize(path, "demo")
    assert metrics["initial_verified_hints"] == 2
    assert metrics["corrected_after_first_hint"] == 1
    assert metrics["correction_rate"] == 0.5


def test_revisions_cannot_link_to_another_problem(pilot):
    client, _ = pilot
    first = submit(client, ["x=3"]).json()
    assert submit(client, ["x=5"], previous=first["attempt_id"], problem="linear-balance").status_code == 400
    assert submit(client, ["x=2"], previous="missing").status_code == 400


def test_rating_bounds_and_unknown_attempt(pilot):
    client, _ = pilot
    first = submit(client, ["x=3"]).json()
    url = f"/api/attempts/{first['attempt_id']}/rating"
    for value in [0, 6, "5", True]:
        assert client.post(url, json={"rating": value}).status_code == 422
    assert client.post("/api/attempts/missing/rating", json={"rating": 5}).status_code == 404
