"""Independent fail-closed validator for proposed rowing coaching.

The generator must never control the separately supplied evidence and cue
catalogue. Numerical checks cannot verify arbitrary explanatory free text.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from numbers import Real

from .evidence import MIN_SAMPLE_STROKES, validate_reference_graph
from .strokes import FAULTS

_FIELDS = frozenset({
    "finding_id", "seat_id", "stroke_ids", "fault_code", "cue_id",
    "observed_count", "analyzed_strokes", "observed_fraction", "explanation",
})


def _blocked(*errors: str) -> dict:
    """Never return a rejected candidate's potentially misleading text."""
    return {"released": None, "errors": list(dict.fromkeys(errors)), "warnings": []}


def validate_candidate(candidate, *, evidence_snapshot, reviewed_cues) -> dict:
    """Check IDs, counted observations, eligibility and independent cue review.

    The caller must protect trusted inputs: a snapshot checksum detects
    accidental changes but is not a signature against a deliberate editor.
    """
    try:
        return _validate_candidate(candidate, evidence_snapshot, reviewed_cues)
    except (TypeError, ValueError, KeyError, OverflowError):
        return _blocked("invalid_evidence")


def _validate_candidate(candidate, evidence_snapshot, reviewed_cues) -> dict:
    if not validate_reference_graph(evidence_snapshot):
        return _blocked("invalid_evidence")
    if not isinstance(candidate, Mapping):
        return _blocked("invalid_candidate")
    if set(candidate) - _FIELDS:
        return _blocked("unexpected_field")
    if set(candidate) != _FIELDS:
        return _blocked("invalid_candidate")
    if any(not isinstance(candidate[key], str) or not candidate[key].strip()
           or len(candidate[key]) > (1000 if key == "explanation" else 128)
           for key in ("finding_id", "seat_id", "fault_code", "cue_id", "explanation")):
        return _blocked("invalid_candidate")
    ids = candidate["stroke_ids"]
    if not isinstance(ids, list) or not ids or len(ids) > 5000 or any(
        not isinstance(x, str) or not x or len(x) > 128 for x in ids
    ) or len(set(ids)) != len(ids):
        return _blocked("invalid_candidate")
    if (type(candidate["observed_count"]) is not int or
            type(candidate["analyzed_strokes"]) is not int or
            isinstance(candidate["observed_fraction"], bool) or
            not isinstance(candidate["observed_fraction"], Real) or
            not math.isfinite(float(candidate["observed_fraction"]))):
        return _blocked("invalid_candidate")
    if not isinstance(reviewed_cues, Mapping):
        return _blocked("unapproved_cue")

    seats = {x.get("id") for x in evidence_snapshot.get("seats", [])
             if isinstance(x, Mapping)}
    findings = {x.get("id"): x for x in evidence_snapshot.get("findings", [])
                if isinstance(x, Mapping)}
    strokes = {x.get("id"): x for x in evidence_snapshot.get("strokes", [])
               if isinstance(x, Mapping)}
    errors = []
    if candidate["seat_id"] not in seats:
        errors.append("unknown_seat")
    finding = findings.get(candidate["finding_id"])
    if finding is None:
        errors.append("unknown_finding")
    else:
        if finding.get("seat_id") != candidate["seat_id"]:
            errors.append("unknown_seat")
        if candidate["fault_code"] != finding.get("fault_code"):
            errors.append("fault_mismatch")
        supported_ids = finding.get("stroke_ids", [])
        if (set(ids) != set(supported_ids) or
                any(strokes.get(sid, {}).get("seat_id") != candidate["seat_id"] or
                    candidate["fault_code"] not in strokes.get(sid, {}).get("fault_codes", [])
                    for sid in ids)):
            errors.append("unknown_stroke")
        if (candidate["observed_count"] != finding.get("observed_count") or
                candidate["analyzed_strokes"] != finding.get("analyzed_strokes") or
                not math.isclose(float(candidate["observed_fraction"]),
                                 float(finding.get("observed_fraction", -1)),
                                 rel_tol=0, abs_tol=1e-9)):
            errors.append("incorrect_quantity")
        eligible = finding.get("eligible_strokes")
        if (finding.get("status") != "reviewed_supported" or
                finding.get("coaching_eligible") is not True or
                type(eligible) is not int or eligible < MIN_SAMPLE_STROKES or
                eligible < finding.get("observed_count", 0)):
            errors.append("insufficient_evidence")

    cue = reviewed_cues.get(candidate["cue_id"])
    fault_codes = cue.get("fault_codes") if isinstance(cue, Mapping) else None
    if (not isinstance(cue, Mapping) or cue.get("review_status") != "approved" or
            not isinstance(cue.get("reviewed_by"), str) or
            not cue["reviewed_by"].strip() or
            not isinstance(fault_codes, list) or not fault_codes or
            len(fault_codes) > len(FAULTS) or
            any(type(code) is not str or code not in FAULTS
                for code in fault_codes) or
            len(set(fault_codes)) != len(fault_codes)):
        errors.append("unapproved_cue")
    elif candidate["fault_code"] not in fault_codes:
        errors.append("cue_fault_mismatch")
    if errors:
        return _blocked(*errors)
    return {"released": dict(candidate), "errors": [],
            "warnings": ["free_text_unverified"]}
