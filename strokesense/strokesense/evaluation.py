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


# Exact v1 contract of the separate, blank fault-review grid export.
# This parser cannot authenticate the operator's claimed reviewer identity.
REVIEW_CSV_V1_COLUMNS = (
    "schema_version", "seat_id", "seat", "stroke_id", "stroke_index",
    "fault_code", "catch_seconds", "video_seek_seconds", "predicted",
    "coach_fault_present", "coach_comments", "review_status",
)


def _reviewed_csv_records(payload: bytes, *, clip_id: str, group_id: str,
                          split: str) -> list[dict]:
    """Convert only explicitly completed v1 rows into evaluation records."""
    import csv
    import io
    import math
    import re

    text = payload.decode("utf-8")
    if "\x00" in text:
        raise ValueError("invalid CSV contents")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames != list(REVIEW_CSV_V1_COLUMNS):
        raise ValueError("unknown or ambiguous review schema")
    records = []
    for row in reader:
        if (not isinstance(row, dict)
                or set(row) != set(REVIEW_CSV_V1_COLUMNS)
                or any(type(value) is not str for value in row.values())
                or row["schema_version"] != "1"
                or row["review_status"] != "reviewed"
                or row["predicted"] not in ("0", "1")
                or row["coach_fault_present"] not in ("0", "1")
                or re.fullmatch(r"(?:0|[1-9][0-9]*)", row["stroke_index"]) is None):
            raise ValueError("invalid or unreviewed CSV opportunity")
        try:
            catch = float(row["catch_seconds"])
            seek = (float(row["video_seek_seconds"])
                    if row["video_seek_seconds"] else None)
        except ValueError as exc:
            raise ValueError("invalid evidence time") from exc
        if (not math.isfinite(catch) or catch < 0 or
                (seek is not None and
                 (not math.isfinite(seek) or not 0 <= seek <= 120))):
            raise ValueError("invalid evidence time")
        if len(records) >= MAX_RECORDS:
            raise ValueError("too many review opportunities")
        records.append({
            "clip_id": clip_id, "seat_id": row["seat_id"],
            "stroke_id": row["stroke_id"], "fault_code": row["fault_code"],
            "actual": row["coach_fault_present"] == "1",
            "predicted": row["predicted"] == "1",
            "review_status": "reviewed", "group_id": group_id, "split": split,
        })
    if not records:
        raise ValueError("empty review worksheet")
    return records


MAX_INPUT_BYTES = 2 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    """Bounded local evaluation CLI; never echo private input paths or rows."""
    import argparse
    import csv
    import json
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(
        description="Aggregate explicitly reviewed fault opportunities locally")
    parser.add_argument("input", help="Local JSON evaluation records or reviewed CSV")
    parser.add_argument("--review-csv", action="store_true",
                        help="Treat input as a manually completed v1 fault-review grid")
    parser.add_argument("--clip-id", default=None,
                        help="Opaque local clip identifier for CSV mode only")
    parser.add_argument("--group-id", default=None,
                        help="Opaque session/athlete grouping for CSV mode only")
    parser.add_argument("--split", default=None,
                        help="Explicit development or heldout evaluation split")
    args = parser.parse_args(argv)
    try:
        path = Path(args.input).expanduser()
        if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("invalid input")
        with path.open("rb") as stream:
            payload = stream.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("oversized input")
        if args.review_csv:
            if (not args.clip_id or not args.group_id or
                    args.split not in _SPLITS):
                raise ValueError("explicit evaluation grouping is required")
            rows = _reviewed_csv_records(
                payload, clip_id=args.clip_id, group_id=args.group_id,
                split=args.split,
            )
        else:
            if any(option is not None for option in
                   (args.clip_id, args.group_id, args.split)):
                raise ValueError("CSV-only options require --review-csv")
            rows = json.loads(payload.decode("utf-8"))
        result = evaluate_fault_records(rows)
        if args.review_csv:
            # Passing a parser cannot establish real human reviewer legitimacy.
            result["labels_independently_verified"] = False
        output = json.dumps(result, sort_keys=True, allow_nan=False)
    except (OSError, ValueError, UnicodeError, TypeError, OverflowError, csv.Error):
        print("Evaluation error: input unavailable or invalid", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
