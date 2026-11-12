"""Offline tests for explicit-denominator fault evaluation; all labels synthetic.

No athlete records, video inference, or real coach-reviewed ground truth.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def evaluate(rows):
    # A test-first behavioral assertion, not a missing-environment import error.
    assert importlib.util.find_spec("strokesense.evaluation") is not None, (
        "The requested evaluated-opportunity feature has not been implemented")
    return importlib.import_module("strokesense.evaluation").evaluate_fault_records(rows)


def row(i, *, actual=False, predicted=False, group="synthetic-session-a",
        split="development", clip="opaque-private-clip", code="early_arms"):
    return {
        "clip_id": clip, "seat_id": "seat1", "stroke_id": f"stroke-{i}",
        "fault_code": code, "actual": actual, "predicted": predicted,
        "review_status": "reviewed", "group_id": group, "split": split,
    }


class LabeledEvaluationTests(unittest.TestCase):
    def test_reviewed_confusion_counts_explicit_denominators_and_order(self):
        rows = [
            row(1, actual=True, predicted=True),
            row(2, actual=False, predicted=True),
            row(3, actual=True, predicted=False),
            row(4, actual=False, predicted=False),
        ]
        report = evaluate(rows)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["evaluated_opportunities"], 4)
        counts = report["by_split"]["development"]["early_arms"]
        self.assertEqual(
            {k: counts[k] for k in ("tp", "fp", "fn", "tn", "opportunities")},
            {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "opportunities": 4},
        )
        self.assertEqual(counts["precision_numerator"], 1)
        self.assertEqual(counts["precision_denominator"], 2)
        self.assertEqual(counts["recall_numerator"], 1)
        self.assertEqual(counts["recall_denominator"], 2)
        self.assertEqual(counts["precision"], 0.5)
        self.assertEqual(counts["recall"], 0.5)
        self.assertEqual(report, evaluate(list(reversed(rows))))
        self.assertNotIn("opaque-private-clip", json.dumps(report))
        self.assertNotIn("synthetic-session-a", json.dumps(report))

    def test_zero_denominators_explicitly_undefined(self):
        report = evaluate([row(1, group="group-b", clip="clip-b",
                               split="heldout")])
        counts = report["by_split"]["heldout"]["early_arms"]
        self.assertEqual((counts["tp"], counts["tn"]), (0, 1))
        self.assertEqual((counts["precision_denominator"],
                          counts["recall_denominator"]), (0, 0))
        self.assertIsNone(counts["precision"])
        self.assertIsNone(counts["recall"])

    def test_unreviewed_unknown_invalid_or_unbounded_inputs_rejected(self):
        for modification in (
            {"review_status": "unreviewed"},
            {"fault_code": "fabricated_fault"},
            {"actual": "true"},
            {"predicted": 1},
            {"split": "unassigned"},
            {"group_id": ""},
            {"stroke_id": ""},
        ):
            bad = row(1)
            bad.update(modification)
            with self.subTest(change=modification), self.assertRaises(ValueError):
                evaluate([bad])
        with self.assertRaises(ValueError):
            evaluate("not a list")
        with self.assertRaises(ValueError):
            evaluate([row(1)] * 10001)

    def test_duplicate_opportunities_and_cross_split_group_leakage_rejected(self):
        first = row(1)
        with self.assertRaises(ValueError):
            evaluate([first, dict(first)])
        second = row(2, group="synthetic-session-a", split="heldout",
                     clip="opaque-other-clip")
        with self.assertRaises(ValueError):
            evaluate([first, second])


if __name__ == "__main__":
    unittest.main()
