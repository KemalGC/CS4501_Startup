"""Synthetic test-first correction loop; never invokes a live model."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_validation import trusted_synthetic_fixture


class CorrectionLoopTests(unittest.TestCase):
    def test_reject_then_correct_with_machine_readable_feedback(self):
        from strokesense import correction
        snap, candidate, cues = trusted_synthetic_fixture()
        calls = []

        def generator(attempt, errors):
            calls.append((attempt, list(errors)))
            answer = copy.deepcopy(candidate)
            if attempt == 1:
                answer["observed_count"] = 99
            return answer

        result = correction.run_correction(
            generator, evidence_snapshot=snap, reviewed_cues=cues
        )
        self.assertEqual(result["status"], "released")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["released"], candidate)
        self.assertEqual(calls, [(1, []), (2, ["incorrect_quantity"])])
        self.assertIn("free_text_unverified", result["warnings"])

    def test_persistent_failures_withheld_after_three_attempts(self):
        from strokesense import correction
        snap, candidate, cues = trusted_synthetic_fixture()
        candidate["stroke_ids"] = ["nonexistent-id"]
        calls = []

        def generator(attempt, errors):
            calls.append(attempt)
            return candidate

        result = correction.run_correction(
            generator, evidence_snapshot=snap, reviewed_cues=cues
        )
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 3)
        self.assertIsNone(result["released"])
        self.assertIn("unknown_stroke", result["errors"])
        self.assertNotIn(candidate["explanation"], json.dumps(result))

    def test_explicit_attempt_cap_respected(self):
        from strokesense import correction
        snap, cand, cues = trusted_synthetic_fixture()
        cand["finding_id"] = "fake"
        called = []
        result = correction.run_correction(
            lambda attempt, errors: called.append(attempt) or dict(cand),
            evidence_snapshot=snap, reviewed_cues=cues, max_attempts=2
        )
        self.assertEqual(called, [1, 2])
        self.assertIsNone(result["released"])

    def test_provider_exception_fails_closed_without_exposing_text(self):
        from strokesense import correction
        snap, cand, cues = trusted_synthetic_fixture()

        def generator(attempt, errors):
            raise RuntimeError("private bad provider response with athlete name")

        result = correction.run_correction(
            generator, evidence_snapshot=snap, reviewed_cues=cues
        )
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["errors"], ["generation_failed"])
        self.assertNotIn("athlete", json.dumps(result))

    def test_unreviewed_v1_evidence_never_releases(self):
        from strokesense import correction, evidence
        snap, cand, cues = trusted_synthetic_fixture()
        finding = snap["findings"][0]
        finding["coaching_eligible"] = False
        finding["eligible_strokes"] = None
        finding["status"] = "candidate_unreviewed"
        payload = {key: value for key, value in snap.items()
                   if key != "snapshot_sha256"}
        snap["snapshot_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False).encode()
        ).hexdigest()
        self.assertTrue(evidence.verify_evidence_snapshot(snap))
        result = correction.run_correction(
            lambda attempt, errors: dict(cand),
            evidence_snapshot=snap, reviewed_cues=cues,
        )
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 3)
        self.assertIsNone(result["released"])

    def test_external_mutation_during_generation_cannot_change_trusted_inputs(self):
        from strokesense import correction
        snap, cand, cues = trusted_synthetic_fixture()

        def generator(attempt, errors):
            snap["findings"][0]["observed_count"] = 999
            cues.clear()
            return dict(cand)

        result = correction.run_correction(
            generator, evidence_snapshot=snap, reviewed_cues=cues,
        )
        self.assertEqual(result["status"], "released")
        self.assertEqual(result["attempts"], 1)

    def test_max_attempts_must_be_one_to_three(self):
        from strokesense import correction
        snap, cand, cues = trusted_synthetic_fixture()
        for cap in (0, 4, -1, True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                correction.run_correction(
                    lambda attempt, errors: dict(cand),
                    evidence_snapshot=snap, reviewed_cues=cues,
                    max_attempts=cap,
                )


if __name__ == "__main__":
    unittest.main()
