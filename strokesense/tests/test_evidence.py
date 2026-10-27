"""Test-first offline contract for evidence extracted from synthetic stroke records.

No video inference or LLM provider is called. Student-team review is pending.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1])))


def sample_metrics():
    return {
        "sync": {},
        "rowers": [
            {
                "seat": "Stroke",
                "track": 2,
                "summary": {"n_strokes": 999, "issues": [{"code": "early_arms", "frac": 0.99}]},
                "strokes": [
                    {"idx": 0, "catch": 10, "catch_t": 10.1, "finish": 20,
                     "next_catch": 40, "faults": ["early_arms"]},
                    {"idx": 1, "catch": 40, "catch_t": 40.0, "finish": 50,
                     "next_catch": 70, "faults": []},
                    {"idx": 2, "catch": 70, "catch_t": 70.2, "finish": 80,
                     "next_catch": 100, "faults": ["early_arms"]},
                ],
            }
        ],
    }


class EvidenceSnapshotTests(unittest.TestCase):
    def build(self, metrics=None, **changes):
        from strokesense import evidence
        opts = dict(analysis_key="private/source/path|settings|model",
                    fps=20.0, start_seconds=5.0)
        opts.update(changes)
        return evidence.build_evidence_snapshot(
            sample_metrics() if metrics is None else metrics, **opts
        )

    def test_deterministic_versioned_and_content_addressed(self):
        from strokesense import evidence
        a = self.build()
        b = self.build()
        self.assertEqual(a, b)
        self.assertEqual(a["schema_version"], 1)
        self.assertTrue(a["analysis_id"].startswith("analysis_"))
        self.assertTrue(evidence.verify_evidence_snapshot(a))
        self.assertEqual(len(a["strokes"]), 3)
        self.assertEqual(len({r["id"] for r in a["strokes"]}), 3)
        self.assertEqual(a["seats"][0]["seat"], "Stroke")

    def test_private_source_not_leaked_and_distinct_analysis_ids(self):
        a = self.build()
        b = self.build(analysis_key="another/private/path|settings|model")
        self.assertNotEqual(a["analysis_id"], b["analysis_id"])
        self.assertNotEqual(a["strokes"][0]["id"], b["strokes"][0]["id"])
        self.assertNotIn("private/source/path", json.dumps(a))
        self.assertNotIn("another/private/path", json.dumps(b))

    def test_fractional_source_timestamps(self):
        a = self.build()
        first = a["strokes"][0]
        self.assertAlmostEqual(first["catch_seconds"], 5.505)
        self.assertAlmostEqual(first["finish_seconds"], 6.0)
        self.assertAlmostEqual(first["next_catch_seconds"], 7.0)
        self.assertLess(first["catch_seconds"], first["finish_seconds"])

    def test_counts_are_from_strokes_not_untrusted_summary(self):
        a = self.build()
        finding = a["findings"][0]
        self.assertEqual(finding["fault_code"], "early_arms")
        self.assertEqual(finding["observed_count"], 2)
        self.assertEqual(finding["analyzed_strokes"], 3)
        self.assertAlmostEqual(finding["observed_fraction"], 2 / 3)
        self.assertEqual(len(finding["stroke_ids"]), 2)
        self.assertEqual(finding["status"], "candidate_unreviewed")
        self.assertIsNone(finding["eligible_strokes"])
        self.assertFalse(finding["coaching_eligible"])

    def test_missing_and_low_sample_explicitly_abstain(self):
        data = sample_metrics()
        data["rowers"][0]["strokes"] = []
        empty = self.build(data)
        self.assertEqual(empty["seats"][0]["status"], "insufficient_strokes")
        self.assertEqual(empty["findings"], [])
        data["rowers"][0]["strokes"] = [sample_metrics()["rowers"][0]["strokes"][0]]
        one = self.build(data)
        self.assertEqual(one["seats"][0]["status"], "insufficient_strokes")
        self.assertEqual(one["findings"][0]["status"], "insufficient_evidence")
        self.assertFalse(one["findings"][0]["coaching_eligible"])

    def test_two_seats_with_same_indices_have_distinct_ids(self):
        data = sample_metrics()
        other = copy.deepcopy(data["rowers"][0])
        other["seat"] = "Bow"
        other["track"] = 9
        data["rowers"].append(other)
        a = self.build(data)
        self.assertEqual(len(a["strokes"]), 6)
        self.assertEqual(len({s["id"] for s in a["strokes"]}), 6)
        self.assertEqual(len(a["findings"]), 2)

    def test_bad_fps_and_offset_rejected(self):
        for fps in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                self.build(fps=fps)
        with self.assertRaises(ValueError):
            self.build(start_seconds=float("nan"))
        with self.assertRaises(ValueError):
            self.build(analysis_key="")

    def test_bad_stroke_order_and_duplicate_index_rejected(self):
        for bad in (
            {"catch": 20, "finish": 20},
            {"catch": 30, "finish": 20},
            {"finish": 99, "next_catch": 80},
            {"catch": -1},
            {"catch_t": float("nan")},
        ):
            data = sample_metrics()
            data["rowers"][0]["strokes"][0].update(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.build(data)
        data = sample_metrics()
        data["rowers"][0]["strokes"][1]["idx"] = 0
        with self.assertRaises(ValueError):
            self.build(data)

    def test_unknown_or_repeated_fault_code_rejected(self):
        for faults in (["not_a_real_fault"], ["early_arms", "early_arms"]):
            data = sample_metrics()
            data["rowers"][0]["strokes"][0]["faults"] = faults
            with self.subTest(faults=faults), self.assertRaises(ValueError):
                self.build(data)

    def test_modified_record_fails_snapshot_integrity(self):
        from strokesense import evidence
        a = self.build()
        a["findings"][0]["observed_count"] = 99
        self.assertFalse(evidence.verify_evidence_snapshot(a))
        self.assertFalse(evidence.verify_evidence_snapshot({"unexpected": "data"}))

    def test_report_json_contains_backward_compatible_evidence(self):
        from strokesense import report, evidence
        row = sample_metrics()["rowers"][0]
        fake = types.SimpleNamespace(
            seat=row["seat"], tid=row["track"], summary=row["summary"],
            sync_ms=None, strokes=[types.SimpleNamespace(
                to_dict=lambda v=v: dict(v)
            ) for v in row["strokes"]],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.json"
            returned = report.build_json(
                [fake], {}, path, analysis_key="opaque-analysis",
                fps=20.0, start_seconds=5.0,
            )
            self.assertEqual(returned, path)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("rowers", data)
        self.assertIn("sync", data)
        self.assertEqual(len(data["rowers"][0]["strokes"]), 3)
        self.assertTrue(evidence.verify_evidence_snapshot(data["evidence"]))


if __name__ == "__main__":
    unittest.main()
