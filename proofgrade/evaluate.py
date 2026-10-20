"""Run developer regression cases; do not confuse these with pilot evidence."""

import argparse
import json
from pathlib import Path

from proofgrade.algebra import check_solution
from proofgrade.problems import get_problem


def evaluate(split="evaluation"):
    cases = json.loads((Path(__file__).parent / "data" / "evaluation.json").read_text())
    cases = [case for case in cases if split == "all" or case["split"] == split]
    failures = []
    error_cases = 0
    error_matches = 0
    for case in cases:
        result = check_solution(get_problem(case["problem_id"]).equation, case["steps"])
        if (result.status, result.first_error_step) != (case["expected_status"], case["expected_first_error"]):
            failures.append(case["id"])
        if case["expected_status"] == "incorrect":
            error_cases += 1
            error_matches += result.status == "incorrect" and result.first_error_step == case["expected_first_error"]
    return {"split": split, "cases": len(cases), "matching_cases": len(cases) - len(failures),
            "first_error_cases": error_cases, "first_error_matches": error_matches,
            "instructor_reviewed_cases": sum(case["review_status"] == "reviewed" for case in cases),
            "failures": failures, "evidence_type": "developer fixtures; instructor review and student pilot pending"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "evaluation", "all"], default="evaluation")
    args = parser.parse_args()
    result = evaluate(args.split)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["failures"]))


if __name__ == "__main__":
    main()
