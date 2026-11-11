"""Synthetic geometry tests for conservative bow-to-stroke inference."""
from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.seat_orientation import infer_dominant_seats
from strokesense.hosted_dashboard import _verified_seat_mapping, _report_seat_mapping, build_dashboard


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

    def test_dashboard_accepts_only_full_run_matched_seat_order(self):
        proposed = infer_dominant_seats(tracks(), crew_facing=1, n_seats=8)
        ids = [f"R{i}" for i in range(1, 9)]
        self.assertEqual(_verified_seat_mapping(proposed, ids)["status"], "auto")
        self.assertEqual(_verified_seat_mapping(proposed, ids[:-1])["status"], "uncertain")
        tampered = {**proposed, "assignments": {**proposed["assignments"],
                    "R1": "Stroke seat"}}
        self.assertEqual(_verified_seat_mapping(tampered, ids)["status"], "uncertain")

    def test_prepared_report_uses_confirmed_stroke_to_bow_seats(self):
        ids = [f"R{i}" for i in range(1, 9)]
        mapping = _report_seat_mapping(None, ids, prepared=True)
        self.assertEqual(mapping["status"], "prepared")
        self.assertEqual(mapping["travel_direction"], "right")
        self.assertEqual([mapping["assignments"][i] for i in ids], [
            "Stroke seat", "Seat 7", "Seat 6", "Seat 5", "Seat 4",
            "Seat 3", "Seat 2", "Bow seat",
        ])

    def test_prepared_report_never_relabels_partial_crew(self):
        ids = [f"R{i}" for i in range(1, 9) if i != 4]
        mapping = _report_seat_mapping(None, ids, prepared=True)
        self.assertEqual(mapping["status"], "uncertain")
        self.assertEqual(mapping["assignments"], {})

    def test_uploaded_report_respects_verified_reverse_orientation(self):
        ids = [f"R{i}" for i in range(1, 9)]
        mapping = infer_dominant_seats(tracks(facing=1), crew_facing=1, n_seats=8)
        verified = _report_seat_mapping(mapping, ids, prepared=False)
        self.assertEqual(verified["status"], "auto")
        self.assertEqual(verified["assignments"]["R1"], "Bow seat")
        self.assertEqual(verified["assignments"]["R8"], "Stroke seat")

    def test_dashboard_exposes_presentation_seats_without_changing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.html"
            report.write_text("<h1>Fixture</h1>", encoding="utf-8")
            metrics = {
                "crew_cadence": {"rate_spm": 31.5},
                "rowers": [
                    {"seat": f"R{i}", "strokes": [{"catch": 0}],
                     "summary": {"n_strokes": 1, "score": 75}, "sync_ms": 5}
                    for i in range(1, 9)
                ],
                "sync": {},
            }
            (root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
            state = SimpleNamespace(snapshot=lambda: {"state": "finished"},
                                    report=report, output_root=root,
                                    run_id="a" * 32, last_end=None)
            prepared = build_dashboard(state, "Prepared rowing clip", prepared=True)
            self.assertEqual([r["id"] for r in prepared["rowers"]],
                             [f"R{i}" for i in range(1, 9)])
            self.assertEqual(prepared["rowers"][0]["seat_label"], "Stroke seat")
            self.assertEqual(prepared["rowers"][7]["seat_label"], "Bow seat")
            uploaded = build_dashboard(state, "Uploaded rowing clip")
            self.assertTrue(all(r["seat_label"] is None for r in uploaded["rowers"]))
            self.assertEqual(uploaded["seat_mapping"]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
