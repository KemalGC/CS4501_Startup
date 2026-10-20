"""Check model candidates before releasing any hint to a student."""

from dataclasses import dataclass
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import sympy as sp

from proofgrade.algebra import CheckResult, UnsupportedInput, X, check_solution, equation, parse_statement

TEMPLATES = {
    "distribution": {
        "direct": "Apply the outside factor to every term inside the parentheses.",
        "question": "Did you multiply every term inside the parentheses by the outside factor?",
    },
    "missing_root": {
        "direct": "Keep every real solution of the previous equation when you write this step.",
        "question": "Does this step still include every real solution of the previous equation?",
    },
    "extra_root": {
        "direct": "Check that the new equation has not introduced an extra solution.",
        "question": "Would every solution of this new equation also satisfy the previous equation?",
    },
    "equivalence": {
        "direct": "Recheck the arithmetic and use operations that preserve the solutions on both sides.",
        "question": "What operation did you apply, and does it preserve the solutions on both sides?",
    },
}


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step: int = Field(ge=1, le=20)
    before: str = Field(min_length=1, max_length=256)
    after: str = Field(min_length=1, max_length=256)
    correction: str = Field(min_length=1, max_length=256)
    final_solution: str = Field(min_length=1, max_length=256)
    category: Literal["distribution", "missing_root", "extra_root", "equivalence"]
    hint_style: Literal["direct", "question"]


class CandidateProvider(Protocol):
    mode: str

    def generate(self, context: dict, failures: list[str]) -> dict: ...


class ProviderUnavailable(Exception):
    pass


def verified_categories(before: str, after: str) -> list[str]:
    old = parse_statement(before).solutions
    new = parse_statement(after).solutions
    categories = ["equivalence"]
    if isinstance(old, sp.FiniteSet) and isinstance(new, sp.FiniteSet):
        if new.is_proper_subset(old):
            categories.insert(0, "missing_root")
        elif old.is_proper_subset(new):
            categories.insert(0, "extra_root")
    if " or " not in before and " or " not in after:
        old_sides = before.split("=")
        new_sides = equation(after)
        original_sides = equation(before)
        for index, side in enumerate(old_sides):
            match = re.fullmatch(r"([+-]?\d+)\(x([+-]\d+)\)", side.replace(" ", ""))
            if match:
                factor, constant = map(int, match.groups())
                if (factor != 1 and constant != 0
                        and new_sides[index] == factor * X + constant
                        and new_sides[1 - index] == original_sides[1 - index]):
                    categories.insert(0, "distribution")
    return categories


def validate_candidate(candidate: Candidate, context: dict, trusted_answer: str):
    if candidate.step != context["step"]:
        raise ValueError("The step index does not match the verified first error.")
    if candidate.before != context["before"] or candidate.after != context["after"]:
        raise ValueError("The cited equations do not match the submitted transition.")
    if candidate.category not in context["allowed_categories"]:
        raise ValueError("The proposed error category is not supported by the checked transition.")
    expected = parse_statement(context["before"]).solutions
    correction = parse_statement(candidate.correction)
    if correction.solutions != expected:
        raise ValueError(f"Correction changes the solution set: expected {expected}, got {correction.solutions}.")
    if candidate.correction.replace(" ", "") == context["before"].replace(" ", ""):
        raise ValueError("The correction only repeats the previous equation; propose a valid next transition.")
    final = parse_statement(candidate.final_solution)
    if not final.complete or final.solutions != parse_statement(trusted_answer).solutions:
        raise ValueError("The final solution is incomplete or disagrees with the trusted answer key.")


@dataclass(frozen=True)
class Feedback:
    check: CheckResult
    hint_status: str
    hint: str | None = None
    attempts: int = 0
    rejected_candidates: int = 0


def generate_feedback(original: str, steps: list[str], trusted_answer: str,
                      provider: CandidateProvider) -> Feedback:
    check = check_solution(original, steps)
    if check.status != "incorrect":
        return Feedback(check, "not_needed")
    try:
        answer = parse_statement(trusted_answer)
        if not answer.complete or answer.solutions != parse_statement(original).solutions:
            return Feedback(check, "manual_review")
        index = check.first_error_step
        before = original if index == 1 else steps[index - 2]
        after = steps[index - 1]
        context = {"original": original, "step": index, "before": before, "after": after,
                   "allowed_categories": verified_categories(before, after)}
    except UnsupportedInput:
        return Feedback(check, "manual_review")
    failures = []
    for attempt in range(1, 4):
        try:
            raw = provider.generate(context, failures.copy())
            candidate = Candidate.model_validate(raw)
            validate_candidate(candidate, context, trusted_answer)
        except ProviderUnavailable:
            return Feedback(check, "unavailable", attempts=attempt, rejected_candidates=len(failures))
        except (ValidationError, UnsupportedInput, ValueError) as error:
            failures.append(str(error)[:1500])
            continue
        return Feedback(check, "verified", TEMPLATES[candidate.category][candidate.hint_style],
                        attempt, len(failures))
    return Feedback(check, "manual_review", attempts=3, rejected_candidates=len(failures))
