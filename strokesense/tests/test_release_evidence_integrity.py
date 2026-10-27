"""Tests-first: independently checked coaching must reject rehashed false evidence.

All approval identities and data here are synthetic fixtures, NOT real reviews.
The provider is patched; no network traffic or credentials are used.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.evidence import verify_evidence_snapshot
from strokesense.validation import validate_candidate
from strokesense.provider import OpenAIChatGenerator, ProviderError
from test_validation import trusted_synthetic_fixture


def _rehash(snapshot):
    payload = {key: value for key, value in snapshot.items()
               if key != "snapshot_sha256"}
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert verify_evidence_snapshot(snapshot)


def _fixture_with_overlap():
    snapshot, candidate, cues = trusted_synthetic_fixture()
    stroke = snapshot["strokes"][1]
    stroke.update(catch_frame=20, finish_frame=30, next_catch_frame=50,
                  catch_seconds=20/15, finish_seconds=30/15,
                  next_catch_seconds=50/15)
    _rehash(snapshot)
    return snapshot, candidate, cues


def _fixture_with_duplicate_finding():
    snapshot, candidate, cues = trusted_synthetic_fixture()
    snapshot["findings"].append(deepcopy(snapshot["findings"][0]))
    _rehash(snapshot)
    return snapshot, candidate, cues


def _fixture_with_broken_reference():
    snapshot, candidate, cues = trusted_synthetic_fixture()
    snapshot["strokes"][1]["seat_id"] = "invented_seat"
    _rehash(snapshot)
    return snapshot, candidate, cues


class ReleaseEvidenceIntegrityTests(unittest.TestCase):
    def test_valid_synthetic_reviewed_fixture_still_passes(self):
        snap, candidate, cues = trusted_synthetic_fixture()
        result = validate_candidate(candidate, evidence_snapshot=snap,
                                    reviewed_cues=cues)
        self.assertEqual(result["released"], candidate)
        self.assertIn("free_text_unverified", result["warnings"])

    def test_rehashed_structural_conflicts_withheld_by_release_gate(self):
        for fixture in (_fixture_with_overlap,
                        _fixture_with_duplicate_finding,
                        _fixture_with_broken_reference):
            with self.subTest(fixture=fixture.__name__):
                snap, candidate, cues = fixture()
                result = validate_candidate(
                    candidate, evidence_snapshot=snap, reviewed_cues=cues
                )
                self.assertIsNone(result["released"])
                self.assertEqual(result["errors"], ["invalid_evidence"])
                self.assertNotIn(candidate["explanation"], json.dumps(result))

    def test_rehashed_structural_conflicts_never_reach_provider(self):
        for fixture in (_fixture_with_overlap,
                        _fixture_with_duplicate_finding,
                        _fixture_with_broken_reference):
            with self.subTest(fixture=fixture.__name__):
                snap, _, cues = fixture()
                adapter = OpenAIChatGenerator(
                    evidence_snapshot=snap, reviewed_cues=cues,
                    model="synthetic-fixture-model", api_key="synthetic-fixture-only",
                    endpoint="https://example.test/v1/chat/completions",
                )
                with patch("strokesense.provider.urlopen") as send:
                    with self.assertRaises(ProviderError) as captured:
                        adapter(1, [])
                    send.assert_not_called()
                self.assertEqual(str(captured.exception), "invalid_evidence")


if __name__ == "__main__":
    unittest.main()
