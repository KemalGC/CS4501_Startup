"""Seed practice problems. Answer keys stay on the server."""

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    equation: str
    answer: str
    topic: str
    review_status: str = "pending"
    split: str = "development"


PROBLEMS = [Problem(**item) for item in json.loads((Path(__file__).parent / "data" / "practice.json").read_text())]


def get_problem(problem_id: str) -> Problem | None:
    return next((problem for problem in PROBLEMS if problem.id == problem_id), None)
