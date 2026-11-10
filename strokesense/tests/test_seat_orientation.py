"""Synthetic geometry tests for conservative bow-to-stroke inference."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.seat_orientation import infer_dominant_seats


def tracks(*, facing=1, pan_per_frame=0., frames=60):
    out = {}
    for slot in range(8):
        t = np.arange(frames)
        center = 80. + 92 * slot + pan_per_frame * t
        box = np.stack([center - 24, np.full(frames, 30.),
                        center + 24, np.full(frames, 145.)], axis=1)
        kpts = np.zeros((frames, 17, 3))
        for hip, knee in ((11, 13), (12, 14)):
            kpts[:, hip, 0] = center
            kpts[:, knee, 0] = center + facing * 12
            kpts[:, hip, 1] = 100.
            kpts[:, knee, 1] = 110.
            kpts[:, hip, 2] = .95
            kpts[:, knee, 2] = .95
        out[slot] = {"frames": t, "boxes": box, "kpts": kpts}
    return out


class SeatOrientationTests(unittest.TestCase):
    def test_stern_right_means_bow_left_even_when_camera_pans_right(self):
        result = infer_dominant_seats(tracks(facing=1, pan_per_frame=3.),
                                      crew_facing=1, n_seats=8)
        self.assertEqual(result["status"], "auto")
        self.assertEqual(result["travel_direction"], "left")
        self.assertEqual(result["assignments"]["R1"], "Bow seat")
        self.assertEqual(result["assignments"]["R2"], "Seat 2")
        self.assertEqual(result["assignments"]["R8"], "Stroke seat")
        self.assertGreaterEqual(result["confidence"], .9)

    def test_stern_left_reverses_order(self):
        result = infer_dominant_seats(tracks(facing=-1), crew_facing=-1, n_seats=8)
        self.assertEqual(result["status"], "auto")
        self.assertEqual(result["travel_direction"], "right")
        self.assertEqual(result["assignments"]["R1"], "Stroke seat")
        self.assertEqual(result["assignments"]["R8"], "Bow seat")
        self.assertEqual(result["assignments"]["R7"], "Seat 2")

    def test_missing_rower_never_shifts_other_seat_labels(self):
        candidates = tracks()
        candidates.pop(4)
        result = infer_dominant_seats(candidates, crew_facing=1, n_seats=8)
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["assignments"])

    def test_ambiguous_frontal_or_occluded_pose_abstains(self):
        candidates = tracks()
        for item in candidates.values():
            item["kpts"][:, [13, 14], 0] = item["kpts"][:, [11, 12], 0]
        result = infer_dominant_seats(candidates, crew_facing=1, n_seats=8)
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["travel_direction"])

    def test_disagreeing_rowers_abstain(self):
        candidates = tracks()
        for slot in range(4):
            item = candidates[slot]
            item["kpts"][:, [13, 14], 0] = item["kpts"][:, [11, 12], 0] - 12
        result = infer_dominant_seats(candidates, crew_facing=1, n_seats=8)
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["assignments"])

    def test_slot_order_conflict_abstains(self):
        candidates = tracks()
        item = candidates[3]
        item["boxes"][:35, [0, 2]] += 120
        result = infer_dominant_seats(candidates, crew_facing=1, n_seats=8)
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["assignments"])



if __name__ == "__main__":
    unittest.main()
