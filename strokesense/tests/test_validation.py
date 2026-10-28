"""Test-first negative coverage for a strictly independent coaching release gate.

All approvals and reliable evidence in positive tests are synthetic fixtures,
NOT actual human reviews or empirical validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense import evidence


def trusted_synthetic_fixture():
    metrics = {"rowers": [{"seat": "Stroke", "track": 1, "strokes": [
        {"idx": 0, "catch": 10, "finish": 20, "next_catch": 35,
         "faults": ["early_arms"]},
        {"idx": 1, "catch": 35, "finish": 45, "next_catch": 60,
         "faults": []},
        {"idx": 2, "catch": 60, "finish": 70, "next_catch": 85,
         "faults": ["early_arms"]},
    ]}]}
    snapshot = evidence.build_evidence_snapshot(
        metrics, analysis_key="test-fixture-only", fps=15.0
    )
    # TEST-ONLY simulation of future independently validated coverage/review.
    finding = snapshot["findings"][0]
    finding["coaching_eligible"] = True
    finding["eligible_strokes"] = 3
    finding["status"] = "reviewed_supported"
    payload = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    candidate = {
        "finding_id": finding["id"],
        "seat_id": finding["seat_id"],
        "fault_code": "early_arms",
        "stroke_ids": list(finding["stroke_ids"]),
        "observed_count": 2,
        "analyzed_strokes": 3,
        "observed_fraction": 2/3,
        "cue_id": "fixture-cue",
        "explanation": "Synthetic test-only explanation; not coaching advice.",
    }
    cues = {"fixture-cue": {
        "fault_codes": ["early_arms"],
        "review_status": "approved",
        "reviewed_by": "fixture reviewer (not a real approval)",
    }}
    return snapshot, candidate, cues


class IndependentReleaseTests(unittest.TestCase):
    def validate(self, candidate=None, snapshot=None, cues=None):
        from strokesense import validation
        a, b, c = trusted_synthetic_fixture()
        return validation.validate_candidate(
            b if candidate is None else candidate,
            evidence_snapshot=a if snapshot is None else snapshot,
            reviewed_cues=c if cues is None else cues,
        )

    def test_explicitly_approved_synthetic_fixture_releases_with_warning(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        result = self.validate(candidate, snapshot, cues)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["released"], candidate)
        self.assertIn("free_text_unverified", result["warnings"])

    def test_actual_v1_snapshot_fails_closed(self):
        from strokesense import evidence
        snapshot, candidate, cues = trusted_synthetic_fixture()
        snapshot["findings"][0]["coaching_eligible"] = False
        snapshot["findings"][0]["status"] = "candidate_unreviewed"
        snapshot["findings"][0]["eligible_strokes"] = None
        payload = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
        snapshot["snapshot_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False).encode("utf-8")
        ).hexdigest()
        self.assertTrue(evidence.verify_evidence_snapshot(snapshot))
        result = self.validate(candidate, snapshot, cues)
        self.assertIsNone(result["released"])
        self.assertIn("insufficient_evidence", result["errors"])
        self.assertNotIn("Synthetic test-only explanation", json.dumps(result))

    def test_unknown_finding_seat_and_stroke_ids_withheld(self):
        for field, replacement, error in (
            ("finding_id", "invented-finding", "unknown_finding"),
            ("seat_id", "invented-seat", "unknown_seat"),
            ("stroke_ids", ["invented-stroke"], "unknown_stroke"),
        ):
            snapshot, candidate, cues = trusted_synthetic_fixture()
            candidate[field] = replacement
            result = self.validate(candidate, snapshot, cues)
            with self.subTest(field=field):
                self.assertIsNone(result["released"])
                self.assertIn(error, result["errors"])

    def test_numeric_claims_must_match_saved_observations(self):
        for field, value in (
            ("observed_count", 3), ("analyzed_strokes", 4),
            ("observed_fraction", 0.75),
        ):
            snapshot, candidate, cues = trusted_synthetic_fixture()
            candidate[field] = value
            result = self.validate(candidate, snapshot, cues)
            with self.subTest(field=field):
                self.assertIsNone(result["released"])
                self.assertIn("incorrect_quantity", result["errors"])

    def test_fault_code_and_incomplete_stroke_references_rejected(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        candidate["fault_code"] = "rushed_recovery"
        self.assertIn("fault_mismatch", self.validate(candidate, snapshot, cues)["errors"])
        snapshot, candidate, cues = trusted_synthetic_fixture()
        candidate["stroke_ids"] = candidate["stroke_ids"][:1]
        self.assertIn("unknown_stroke", self.validate(candidate, snapshot, cues)["errors"])

    def test_missing_unreviewed_or_incompatible_cue_rejected(self):
        for cue in (
            {},
            {"fixture-cue": {"fault_codes": ["early_arms"], "review_status": "unreviewed"}},
            {"fixture-cue": {"fault_codes": ["early_arms"], "review_status": "approved"}},
            {"fixture-cue": {"fault_codes": ["overreach"], "review_status": "approved",
                             "reviewed_by": "fixture reviewer"}},
        ):
            snapshot, candidate, _ = trusted_synthetic_fixture()
            result = self.validate(candidate, snapshot, cue)
            with self.subTest(cue=cue):
                self.assertIsNone(result["released"])
                self.assertTrue("unapproved_cue" in result["errors"] or
                                "cue_fault_mismatch" in result["errors"])

    def test_candidate_strings_and_stroke_lists_have_finite_schema_limits(self):
        from strokesense import validation
        cases = (
            ("explanation", "🚣" * 1001),
            ("finding_id", "f" * 129),
            ("seat_id", "s" * 129),
            ("fault_code", "c" * 129),
            ("cue_id", "c" * 129),
            ("stroke_ids", ["s" * 129]),
            ("stroke_ids", [f"distinct-{i}" for i in range(5001)]),
        )
        for field, value in cases:
            with self.subTest(field=field, size=len(value)):
                snap, candidate, cues = trusted_synthetic_fixture()
                candidate[field] = value
                result = validation.validate_candidate(
                    candidate, evidence_snapshot=snap, reviewed_cues=cues,
                )
                self.assertIsNone(result["released"])
                self.assertEqual(result["errors"], ["invalid_candidate"])
                self.assertNotIn("Synthetic test-only explanation",
                                 json.dumps(result))


    def test_candidate_control_and_bidi_spoofing_chars_fail_closed(self):
        """Invisible terminal/BiDi controls must never be locally released."""
        from strokesense.validation import validate_candidate
        cases = (
            ("explanation", "invisible\\x00payload"),
            ("explanation", "escape\\x1b[31mred"),
            ("explanation", "hidden\\u0085control"),
            ("explanation", "spoof\\u202ehtml"),
            ("explanation", "isolate\\u2066fake\\u2069"),
            ("finding_id", "valid\\u202e-looking"),
            ("seat_id", "valid\\x1b-looking"),
            ("stroke_ids", ["valid\\u2066-looking"]),
        )
        for field, item in cases:
            with self.subTest(field=field, value=repr(item)):
                snapshot, candidate, cues = trusted_synthetic_fixture()
                candidate[field] = item
                answer = validate_candidate(
                    candidate, evidence_snapshot=snapshot, reviewed_cues=cues,
                )
                self.assertIsNone(answer["released"])
                self.assertEqual(answer["errors"], ["invalid_candidate"])
                self.assertNotIn("Synthetic test-only explanation",
                                 json.dumps(answer))

    def test_legitimate_multilingual_explanation_newline_and_emoji_remain_allowed(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        candidate["explanation"] = "Technique résumé 🚣‍♂️\\nNext step:\\tpractice"
        answer = self.validate(candidate, snapshot, cues)
        self.assertEqual(answer["released"], candidate)
        self.assertIn("free_text_unverified", answer["warnings"])


    def test_candidate_explanation_boundary_remains_releasable_only_when_reviewed(self):
        snap, candidate, cues = trusted_synthetic_fixture()
        candidate["explanation"] = "🌊" * 1000
        result = self.validate(candidate, snap, cues)
        self.assertEqual(result["released"], candidate)
        self.assertIn("free_text_unverified", result["warnings"])

    def test_approved_cue_fault_codes_require_a_well_formed_reviewed_list(self):
        from strokesense import validation
        malformed = (
            "early_arms", {"early_arms": True}, {"early_arms"}, None,
            [], ["early_arms", "early_arms"],
            ["early_arms", "not_a_known_fault"],
            ["early_arms"] * 100,
        )
        for codes in malformed:
            with self.subTest(type=type(codes).__name__, value=repr(codes)[:50]):
                snap, cand, cues = trusted_synthetic_fixture()
                cues["fixture-cue"]["fault_codes"] = codes
                result = validation.validate_candidate(
                    cand, evidence_snapshot=snap, reviewed_cues=cues,
                )
                self.assertIsNone(result["released"])
                self.assertEqual(result["errors"], ["unapproved_cue"])
                self.assertNotIn(cand["explanation"], json.dumps(result))

    def test_valid_multi_fault_approved_list_still_checks_requested_fault(self):
        from strokesense import validation
        snap, cand, cues = trusted_synthetic_fixture()
        cues["fixture-cue"]["fault_codes"] = ["early_arms", "overreach"]
        self.assertEqual(
            validation.validate_candidate(
                cand, evidence_snapshot=snap, reviewed_cues=cues,
            )["released"], cand,
        )
        cues["fixture-cue"]["fault_codes"] = ["overreach"]
        blocked = validation.validate_candidate(
            cand, evidence_snapshot=snap, reviewed_cues=cues,
        )
        self.assertEqual(blocked["errors"], ["cue_fault_mismatch"])
        self.assertIsNone(blocked["released"])

    def test_candidate_may_not_inject_evidence_or_review_settings(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        candidate["coaching_eligible"] = True
        result = self.validate(candidate, snapshot, cues)
        self.assertIsNone(result["released"])
        self.assertIn("unexpected_field", result["errors"])

    def test_modified_snapshot_refused_without_leaking_advice(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        snapshot["findings"][0]["observed_count"] = 9000
        result = self.validate(candidate, snapshot, cues)
        self.assertEqual(result["errors"], ["invalid_evidence"])
        self.assertIsNone(result["released"])
        self.assertNotIn(candidate["explanation"], json.dumps(result))

    def test_invalid_candidate_shape_or_missing_explanation_withheld(self):
        snapshot, candidate, cues = trusted_synthetic_fixture()
        self.assertIn("invalid_candidate", self.validate([], snapshot, cues)["errors"])
        candidate["explanation"] = ""
        result = self.validate(candidate, snapshot, cues)
        self.assertIsNone(result["released"])
        self.assertIn("invalid_candidate", result["errors"])


if __name__ == "__main__":
    unittest.main()
