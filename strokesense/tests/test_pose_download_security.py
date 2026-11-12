"""The default pose model is installed only after byte-for-byte verification."""
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from strokesense import pose


class PoseDownloadSecurityTests(unittest.TestCase):
    def test_rejects_corrupt_download_without_overwriting_existing_file(self):
        valid = b"signed-model-fixture"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "pose.onnx"
            target.write_bytes(b"bad-old-model")
            with (patch.object(pose, "DEFAULT_MODEL", target),
                  patch.object(pose, "MODEL_BYTES", len(valid)),
                  patch.object(pose, "MODEL_SHA256", hashlib.sha256(valid).hexdigest()),
                  patch.object(pose.urllib.request, "urlopen", return_value=BytesIO(b"tampered-model-data"))):
                with self.assertRaisesRegex(ValueError, "integrity"):
                    pose.ensure_model(target)
                self.assertEqual(target.read_bytes(), b"bad-old-model")
                self.assertEqual(list(Path(folder).glob(".pose-*.download")), [])

    def test_installs_verified_model_and_reuses_it(self):
        valid = b"signed-model-fixture"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "pose.onnx"
            with (patch.object(pose, "DEFAULT_MODEL", target),
                  patch.object(pose, "MODEL_BYTES", len(valid)),
                  patch.object(pose, "MODEL_SHA256", hashlib.sha256(valid).hexdigest()),
                  patch.object(pose.urllib.request, "urlopen", return_value=BytesIO(valid)) as download):
                self.assertEqual(pose.ensure_model(target), target)
                self.assertEqual(pose.ensure_model(target), target)
                self.assertEqual(target.read_bytes(), valid)
                self.assertEqual(download.call_count, 1)


if __name__ == "__main__":
    unittest.main()
