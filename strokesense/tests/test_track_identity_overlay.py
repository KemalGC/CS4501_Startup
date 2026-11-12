"""Annotated video must visibly identify Render's R1..R8 model tracks."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from strokesense import render


class TrackIdentityBadgeTests(unittest.TestCase):
    def test_badges_are_readable_and_clamped_to_frame(self):
        for box in ([1, 1, 70, 100], [120, 12, 190, 170], [174, 45, 215, 150]):
            with self.subTest(box=box):
                frame = np.zeros((180, 220, 3), dtype=np.uint8)
                self.assertTrue(render.draw_track_badge(frame, "R7", box, (80, 200, 255)))
                # The badge includes white, high-contrast letters (not just a box).
                self.assertTrue(np.any(np.all(frame >= 235, axis=2)))
                self.assertGreater(np.count_nonzero(frame), 500)

    def test_missing_or_out_of_frame_boxes_are_ignored(self):
        frame = np.zeros((180, 220, 3), dtype=np.uint8)
        for label, box in (("Bow seat", [10, 10, 90, 100]),
                           ("R2", [1000, 10, 1100, 100]),
                           ("R3", [np.nan, 10, 80, 100]),
                           ("R4", [40, 90, 20, 100])):
            with self.subTest(label=label):
                self.assertFalse(render.draw_track_badge(frame, label, box, (80, 200, 255)))
        self.assertFalse(np.any(frame))

    def test_dominant_overlay_uses_observed_boxes_even_without_pose_joints(self):
        tracks = {
            0: {"frames": np.array([0]), "boxes": np.array([[35, 60, 140, 210]])},
            1: {"frames": np.array([0]), "boxes": np.array([[195, 75, 310, 235]])},
        }
        pose = SimpleNamespace(fps=15, n_frames=1, width=420, height=260,
                               start=0.0, tracks=tracks)
        rowers = [SimpleNamespace(tid=i, seat=f"R{i+1}", strokes=[])
                  for i in range(2)]
        frame = np.zeros((260, 420, 3), dtype=np.uint8)
        writer = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "annotation.mp4"
            with patch.object(render, "_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render, "_open_writer", return_value=(writer, output)), \
                 patch.object(render, "_finalise", return_value=output), \
                 patch.object(render, "iter_frames", return_value=iter([(0, frame)])), \
                 patch.object(render, "draw_rower"), \
                 patch.object(render.cadence, "estimate", return_value={"rate_spm": None}), \
                 patch.object(render, "draw_track_badge", wraps=render.draw_track_badge) as badges:
                render.render_video("synthetic.mp4", pose, rowers, output,
                                    sync={"crew_selection": {"chosen": 2}})
        self.assertEqual([call.args[1] for call in badges.call_args_list], ["R1", "R2"])
        self.assertTrue(all(call.args[2].shape == (4,) for call in badges.call_args_list))
        self.assertEqual(writer.write.call_count, 1)
        rendered = writer.write.call_args.args[0]
        self.assertTrue(np.any(np.all(rendered >= 235, axis=2)))


if __name__ == "__main__":
    unittest.main()
