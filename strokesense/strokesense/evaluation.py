"""Evaluation from explicitly reviewed labeled opportunities; no model execution.

Never equate synthetic fixture pass rates with empirical field accuracy.
Rows are reviewed and eligible stroke/fault opportunities, including negatives.
Opaque identifiers are used internally for duplicate and split-leak checks,
then intentionally omitted from the aggregate output.
"""
from __future__ import annotations

from collections.abc import Mapping

from .strokes import FAULTS

EVALUATION_SCHEMA_VERSION = 1
MAX_RECORDS = 10_000
_FIELDS = frozenset({
    "clip_id", "seat_id", "stroke_id", "fault_code", "actual", "predicted",
    "review_status", "group_id", "split",
})
_SPLITS = frozenset({"development", "heldout"})


def evaluate_fault_records(records) -> dict:
    """Return per-split/fault confusion counts and explicit P/R denominators.

    The caller must independently establish the legitimacy of human labels
    and assign whole session/athlete groups to a split. The function cannot
    verify identities or consent from strings alone. Undefined rates are None.
    """
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError("evaluation requires 1..10000 reviewed opportunities")

    seen = set()
    group_splits = {}
    clip_groups = {}
    counts = {}
    for row in records:
        if not isinstance(row, Mapping) or set(row) != _FIELDS:
            raise ValueError("invalid evaluation record schema")
        for field in ("clip_id", "seat_id", "stroke_id", "group_id"):
            value = row[field]
            if (not isinstance(value, str) or not value.strip()
                    or len(value) > 256
                    or any(ord(char) < 32 for char in value)):
                raise ValueError("invalid opaque evaluation identifier")
        code = row["fault_code"]
        if not isinstance(code, str) or code not in FAULTS:
            raise ValueError("unknown fault code")
        if (type(row["actual"]) is not bool or
                type(row["predicted"]) is not bool):
            raise ValueError("evaluation labels and predictions must be boolean")
        if row["review_status"] != "reviewed":
            raise ValueError("evaluation requires explicitly reviewed labels")
        split = row["split"]
        if not isinstance(split, str) or split not in _SPLITS:
            raise ValueError("evaluation requires development or heldout split")

        clip, group = row["clip_id"], row["group_id"]
        if group in group_splits and group_splits[group] != split:
            raise ValueError("evaluation group leaks across splits")
        if clip in clip_groups and clip_groups[clip] != (group, split):
            raise ValueError("clip belongs to inconsistent evaluation groups")
        group_splits[group] = split
        clip_groups[clip] = (group, split)

        opportunity = (clip, row["seat_id"], row["stroke_id"], code)
        if opportunity in seen:
            raise ValueError("duplicate labeled stroke/fault opportunity")
        seen.add(opportunity)

        bucket = counts.setdefault((split, code), {
            "tp": 0, "fp": 0, "fn": 0, "tn": 0, "opportunities": 0,
        })
        actual, predicted = row["actual"], row["predicted"]
        bucket["tp" if actual and predicted else
               "fp" if predicted else
               "fn" if actual else "tn"] += 1
        bucket["opportunities"] += 1

    by_split = {}
    for split, code in sorted(counts):
        bucket = dict(counts[(split, code)])
        tp, fp, fn = bucket["tp"], bucket["fp"], bucket["fn"]
        p_denom, r_denom = tp + fp, tp + fn
        bucket.update(
            precision_numerator=tp, precision_denominator=p_denom,
            recall_numerator=tp, recall_denominator=r_denom,
            precision=(tp / p_denom if p_denom else None),
            recall=(tp / r_denom if r_denom else None),
        )
        by_split.setdefault(split, {})[code] = bucket

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluated_opportunities": len(records),
        "by_split": by_split,
    }
