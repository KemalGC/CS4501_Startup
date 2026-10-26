"""Cache regression tests. No video decoding, model downloads, or inference.

The import-only OpenCV placeholder lets these tests run in minimal environments;
all video/model entrypoints are mocked, while NPZ serialization is exercised.
"""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from zipfile import ZIP_DEFLATED, ZipFile
import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if importlib.util.find_spec("cv2") is None:
    sys.modules["cv2"] = types.ModuleType("cv2")
    try:
        from strokesense import cli
    finally:
        del sys.modules["cv2"]
else:
    from strokesense import cli

from strokesense.pose import load_detections, save_detections


class PoseCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "crew.mp4"
        self.video.write_bytes(b"source video placeholder")
        self.model = self.root / "pose.onnx"
        self.model.write_bytes(b"model placeholder")
        self.out = self.root / "results"
        self.cache = self.out / self.video.stem / "detections.npz"
        self.dets = [(np.zeros((1, 4)), np.zeros((1, 17, 3)))]
        self.meta = {"fps": 15.0, "width": 640, "height": 480, "start": 0.0, "stride": 2}
        self.messages = []
        self.detector = Mock()
        self.infer = Mock(side_effect=lambda *args, **kw: (self.dets, dict(self.meta)))
        self.patches = [
            patch.object(cli, "PoseDetector", self.detector),
            patch.object(cli, "run_video", self.infer),
            patch.object(cli, "result_from_detections", return_value=types.SimpleNamespace(tracks={})),
            patch.object(cli.crew, "find_rowers", return_value=[]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def analyse(self, **changes):
        settings = dict(video=self.video, out_dir=self.out, model=self.model,
                        single=True, log=self.messages.append)
        settings.update(changes)
        cli.analyse_video(**settings)

    def test_identical_request_reuses_cache_without_initializing_detector(self):
        self.analyse()
        self.analyse()
        self.assertEqual(self.infer.call_count, 1)
        self.assertEqual(self.detector.call_count, 1)
        self.assertTrue(any("Loaded cached pose" in m for m in self.messages))
        dets, meta = load_detections(self.cache)
        self.assertEqual(len(dets), 1)
        self.assertIn('"version":1', meta["cache_identity"])

    def test_changed_extraction_settings_recompute(self):
        for changes in ({"start": 5.0}, {"duration": 20.0}, {"fps": 30.0},
                        {"tiles": None}, {"tiles": [(0, 0, 100, 100)]}):
            with self.subTest(changes=changes):
                self.analyse(reuse=False)
                before = self.infer.call_count
                self.analyse(**changes)
                self.assertEqual(self.infer.call_count, before + 1)

    def test_same_stem_different_video_recomputes(self):
        other = self.root / "other" / self.video.name
        other.parent.mkdir()
        other.write_bytes(self.video.read_bytes())
        self.analyse()
        self.analyse(video=other)
        self.assertEqual(self.infer.call_count, 2)

    def test_replaced_video_and_timestamp_change_recompute(self):
        self.analyse()
        self.video.write_bytes(b"replacement video with a different size")
        self.analyse()
        stat = self.video.stat()
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        self.analyse()
        self.assertEqual(self.infer.call_count, 3)

    def test_model_path_and_same_stat_content_change_recompute(self):
        self.analyse()
        stat = self.model.stat()
        data = self.model.read_bytes()
        self.model.write_bytes(b"x" * len(data))
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.analyse()
        other_model = self.root / "other.onnx"
        other_model.write_bytes(self.model.read_bytes())
        self.analyse(model=other_model)
        self.assertEqual(self.infer.call_count, 3)

    def test_legacy_and_version_mismatch_recompute(self):
        self.cache.parent.mkdir(parents=True)
        save_detections(self.cache, self.dets, self.meta)
        self.analyse()
        with patch.object(cli, "POSE_CACHE_VERSION", 2):
            self.analyse()
        self.assertEqual(self.infer.call_count, 2)
        self.assertTrue(any("outdated" in m for m in self.messages))

    def test_fresh_request_recomputes(self):
        self.analyse()
        self.analyse(reuse=False)
        self.assertEqual(self.infer.call_count, 2)

    def test_corrupt_or_malformed_cache_recomputes(self):
        def bad_counts():
            np.savez(self.cache, counts=[2], boxes=np.zeros((1, 4)),
                     kpts=np.zeros((1, 17, 3)), **self.meta)

        def non_archive():
            with self.cache.open("wb") as stream:
                np.save(stream, np.zeros(2))

        for corrupt in (lambda: self.cache.write_bytes(b"truncated cache"), bad_counts, non_archive):
            with self.subTest(corrupt=corrupt):
                self.analyse(reuse=False)
                corrupt()
                before = self.infer.call_count
                self.analyse()
                self.assertEqual(self.infer.call_count, before + 1)
                self.assertEqual(len(load_detections(self.cache)[0]), 1)
        self.assertTrue(any("Could not read pose cache" in m for m in self.messages))

    def test_first_download_uses_installed_model_identity(self):
        self.model.unlink()
        self.detector.side_effect = lambda *_: self.model.write_bytes(b"downloaded model placeholder")
        self.analyse()
        self.analyse()
        self.assertEqual(self.infer.call_count, 1)

    def test_damaged_compressed_member_recomputes(self):
        self.analyse()
        with ZipFile(self.cache) as archive:
            member = archive.getinfo("counts.npy")
        self.assertEqual(member.compress_type, ZIP_DEFLATED)
        data = bytearray(self.cache.read_bytes())
        name_length, extra_length = struct.unpack_from("<HH", data, member.header_offset + 26)
        payload_start = member.header_offset + 30 + name_length + extra_length
        # Set DEFLATE's first block type to the reserved value, leaving the ZIP
        # directory and member headers valid. This raises zlib.error, not BadZipFile.
        data[payload_start] = (data[payload_start] & ~0x06) | 0x06
        self.cache.write_bytes(data)
        with self.assertRaises(zlib.error):
            load_detections(self.cache)
        self.analyse()
        self.assertEqual(self.infer.call_count, 2)
        self.assertEqual(len(load_detections(self.cache)[0]), 1)
        self.assertTrue(any("Could not read pose cache" in m for m in self.messages))

    def test_source_changes_during_inference_are_not_cached(self):
        def change_video(*args, **kwargs):
            self.video.write_bytes(b"source changed during inference")
            return self.dets, dict(self.meta)
        self.infer.side_effect = change_video
        self.analyse()
        self.assertFalse(self.cache.exists())
        self.assertTrue(any("cache was not saved" in m for m in self.messages))

    def test_empty_detection_cache_round_trip(self):
        self.cache.parent.mkdir(parents=True)
        save_detections(self.cache, [], {**self.meta, "width": 0, "height": 0})
        dets, meta = load_detections(self.cache)
        self.assertEqual(dets, [])
        self.assertEqual(meta["width"], 0)

    def test_failed_write_preserves_previous_cache(self):
        self.analyse()
        previous = self.cache.read_bytes()
        with patch("numpy.savez_compressed", side_effect=OSError("write interrupted")):
            with self.assertRaises(OSError):
                save_detections(self.cache, self.dets, self.meta)
        self.assertEqual(self.cache.read_bytes(), previous)
        self.assertEqual(list(self.cache.parent.glob("detections.npz.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
