"""Seed practice problems. Answer keys stay on the server."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    equation: str
    answer: str
    topic: str


PROBLEMS = [
    Problem("linear-distribution", "Distribute, then solve", "2(x+3)=10", "x=2", "Linear"),
    Problem("linear-balance", "Keep both sides balanced", "3x-5=10", "x=5", "Linear"),
    Problem("linear-fractions", "Work with fractions", "x/2+3=7", "x=8", "Linear"),
    Problem("quadratic-two-roots", "Remember both roots", "x^2=9", "x=-3 or x=3", "Quadratic"),
    Problem("quadratic-factoring", "Find the factors", "x^2-5x+6=0", "x=2 or x=3", "Quadratic"),
    Problem("quadratic-no-real-roots", "Check the real domain", "x^2+4=0", "no real solutions", "Quadratic"),
]


def get_problem(problem_id: str) -> Problem | None:
    return next((problem for problem in PROBLEMS if problem.id == problem_id), None)
