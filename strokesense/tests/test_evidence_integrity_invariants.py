"""Tests-first: structurally contradictory rehashed measurements must not be trusted.

Synthetic, generated fixture data only. A SHA digest detects accidental corruption;
a digest that an adversary can recompute is not an authenticity guarantee.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.evidence import (build_evidence_snapshot,
                                  validate_public_evidence_snapshot,
                                  verify_evidence_snapshot)


def _sample(*, two_seats=False):
    rower = {
        "seat": "Stroke",
        "track": 1,
        "strokes": [
            {"idx": 0, "catch": 10, "finish": 20, "next_catch": 40,
             "faults": ["early_arms"]},
            {"idx": 1, "catch": 40, "finish": 50, "next_catch": 70,
             "faults": []},
            {"idx": 2, "catch": 70, "finish": 80, "next_catch": 100,
             "faults": ["early_arms"]},
        ],
    }
    rowers = [rower]
    if two_seats:
        other = deepcopy(rower)
        other.update(seat="Bow", track=2)
        rowers.append(other)
    return build_evidence_snapshot(
        {"rowers": rowers}, analysis_key="synthetic-fixture-v1", fps=20.0
    )


def _rehash(snapshot):
    payload = {key: value for key, value in snapshot.items()
               if key != "snapshot_sha256"}
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert verify_evidence_snapshot(snapshot)


def _retime(stroke, catch, finish, next_catch):
    stroke["catch_frame"] = catch
    stroke["finish_frame"] = finish
    stroke["next_catch_frame"] = next_catch
    stroke["catch_seconds"] = round(catch / 20.0, 6)
    stroke["finish_seconds"] = round(finish / 20.0, 6)
    stroke["next_catch_seconds"] = round(next_catch / 20.0, 6)


class PublicEvidenceChronologyTests(unittest.TestCase):
    def test_normal_synthetic_snapshot_remains_accepted(self):
        self.assertTrue(validate_public_evidence_snapshot(_sample()))
        self.assertTrue(validate_public_evidence_snapshot(_sample(two_seats=True)))

    def test_overlapping_strokes_rejected_after_valid_rehash(self):
        snapshot = _sample()
        _retime(snapshot["strokes"][1], 20, 30, 50)
        _rehash(snapshot)
        self.assertFalse(validate_public_evidence_snapshot(snapshot))

    def test_out_of_order_frames_rejected_after_valid_rehash(self):
        snapshot = _sample()
        _retime(snapshot["strokes"][1], 110, 120, 140)
        _rehash(snapshot)
        self.assertFalse(validate_public_evidence_snapshot(snapshot))

    def test_duplicate_finding_ids_across_seats_rejected_after_rehash(self):
        snapshot = _sample(two_seats=True)
        self.assertEqual(len(snapshot["findings"]), 2)
        snapshot["findings"][1]["id"] = snapshot["findings"][0]["id"]
        _rehash(snapshot)
        self.assertFalse(validate_public_evidence_snapshot(snapshot))


if __name__ == "__main__":
    unittest.main()
