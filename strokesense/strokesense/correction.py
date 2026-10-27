"""Bounded fail-closed correction loop for structured coaching candidates.

This orchestration is provider-agnostic. It never instantiates an LLM and
never publishes a candidate rejected by the independent validator.
"""
from __future__ import annotations

from copy import deepcopy

from .validation import validate_candidate


def run_correction(
    generator, *, evidence_snapshot, reviewed_cues, max_attempts: int = 3
) -> dict:
    """Generate at most three candidates and release only a validated one.

    Generator signature: generator(attempt_number, prior_error_codes).
    Trusted evidence and cue review are copied before invoking generator and
    never passed as mutable validation controls to a candidate.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be an integer from 1 to 3")
    trusted_evidence = deepcopy(evidence_snapshot)
    trusted_cues = deepcopy(reviewed_cues)
    errors = []
    for attempt in range(1, max_attempts + 1):
        try:
            candidate = generator(attempt, list(errors))
        except Exception:
            # Neither an exception's message nor rejected model text is released.
            return {"status": "withheld", "attempts": attempt,
                    "released": None, "errors": ["generation_failed"],
                    "warnings": []}
        result = validate_candidate(
            candidate, evidence_snapshot=trusted_evidence,
            reviewed_cues=trusted_cues,
        )
        if result["released"] is not None:
            return {"status": "released", "attempts": attempt,
                    "released": result["released"], "errors": [],
                    "warnings": result["warnings"]}
        errors = list(result["errors"])
    return {"status": "withheld", "attempts": max_attempts,
            "released": None, "errors": errors, "warnings": []}
