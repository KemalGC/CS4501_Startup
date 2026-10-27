"""Offline TDD regressions for collision-safe clip result directories.

All sources are synthetic byte placeholders; model/video inference is mocked.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import cli  # noqa: E402


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = self.root / "session_a" / "crew.mp4"
        self.second = self.root / "session_b" / "crew.mp4"
        for video in (self.first, self.second):
            video.parent.mkdir(parents=True)
            video.write_bytes(b"identical synthetic placeholder clip")
        self.out = self.root / "results"
        self.model = self.root / "pose.onnx"
        self.model.write_bytes(b"synthetic model placeholder")
        self.meta = {"fps": 15.0, "width": 640, "height": 480,
                     "start": 0.0, "stride": 2}
        self.dets = [(np.zeros((1, 4)), np.zeros((1, 17, 3)))]

    def _fake_analyses(self, videos):
        infer = Mock(return_value=(self.dets, dict(self.meta)))
        with patch.object(cli, "PoseDetector"), \
                patch.object(cli, "run_video", infer), \
                patch.object(cli, "result_from_detections", return_value=SimpleNamespace(tracks={})), \
                patch.object(cli.crew, "find_rowers", return_value=[]):
            messages = []
            for video in videos:
                self.assertIsNone(cli.analyse_video(
                    video, out_dir=self.out, model=self.model,
                    single=True, log=messages.append))
        return infer.call_count, messages

    def test_same_filename_in_distinct_folders_is_isolated(self):
        a = cli._result_directory(self.first, self.out)
        b = cli._result_directory(self.second, self.out)
        self.assertNotEqual(a, b)
        self.assertEqual(a.parent, self.out)
        self.assertEqual(b.parent, self.out)
        self.assertTrue(a.name.startswith("crew--"))
        self.assertTrue(b.name.startswith("crew--"))

    def test_canonical_alias_and_repeated_source_are_stable(self):
        initial = cli._result_directory(self.first, self.out)
        self.assertEqual(initial, cli._result_directory(self.first, self.out))
        alias = self.root / "alias.mp4"
        try:
            alias.symlink_to(self.first)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this platform")
        self.assertEqual(initial, cli._result_directory(alias, self.out))

    def test_output_root_is_honored_and_parent_path_not_leaked(self):
        other = self.root / "other_results"
        first = cli._result_directory(self.first, self.out)
        alternate = cli._result_directory(self.first, other)
        self.assertEqual(alternate.parent, other)
        self.assertEqual(first.name, alternate.name)
        self.assertNotIn("session_a", first.name)

    def test_legacy_outputs_are_not_overwritten(self):
        legacy = self.out / self.first.stem
        legacy.mkdir(parents=True)
        old_cache = legacy / "detections.npz"
        old_cache.write_bytes(b"pre-existing pose cache")
        old_report = legacy / "report.html"
        old_report.write_text("pre-existing HTML report", encoding="utf-8")
        calls, _ = self._fake_analyses([self.first])
        self.assertEqual(calls, 1)
        self.assertEqual(old_cache.read_bytes(), b"pre-existing pose cache")
        self.assertEqual(old_report.read_text(encoding="utf-8"), "pre-existing HTML report")
        self.assertTrue((cli._result_directory(self.first, self.out) / "detections.npz").exists())

    def test_second_clip_cannot_overwrite_first_clip_artifacts(self):
        calls, _ = self._fake_analyses([self.first])
        self.assertEqual(calls, 1)
        first_out = cli._result_directory(self.first, self.out)
        first_cache = (first_out / "detections.npz").read_bytes()
        artifacts = ("report.html", "metrics.json", "crew_annotated.mp4",
                     "seat_1_catch.jpg", "crew_catch.jpg")
        for artifact in artifacts:
            (first_out / artifact).write_bytes(b"first clip only")
        calls, _ = self._fake_analyses([self.second])
        self.assertEqual(calls, 1)
        self.assertTrue((cli._result_directory(self.second, self.out) / "detections.npz").exists())
        self.assertEqual((first_out / "detections.npz").read_bytes(), first_cache)
        for artifact in artifacts:
            self.assertEqual((first_out / artifact).read_bytes(), b"first clip only")

    def test_same_clip_reuses_valid_pose_cache(self):
        calls, messages = self._fake_analyses([self.first, self.first])
        self.assertEqual(calls, 1)
        self.assertTrue(any("Loaded cached pose" in line for line in messages))


if __name__ == "__main__":
    unittest.main()
