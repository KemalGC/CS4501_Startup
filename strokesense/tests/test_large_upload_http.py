"""Large uploads through real loopback HTTP; synthetic bytes, no inference."""
from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_upload as fixtures
from strokesense import web
from strokesense.registry import list_clips, _stream_sha256


class LargeUploadHTTPTests(unittest.TestCase):
    setUp = fixtures.UploadHTTPTests.setUp
    stop = fixtures.UploadHTTPTests.stop
    request = fixtures.UploadHTTPTests.request
    upload = fixtures.UploadHTTPTests.upload

    def send_video(self, size, *, filename="synthetic.mp4", header=None):
        boundary = "LargeUploadBoundary2026"
        header = fixtures.SYNTHETIC_MP4 if header is None else header
        digest = hashlib.sha256()
        # Disk-backed client and server: never build a 150 MiB bytes fixture.
        with tempfile.TemporaryFile() as body:
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; '
                        f'name="video"; filename="{filename}"\r\n'
                        'Content-Type: application/octet-stream\r\n\r\n').encode())
            body.write(header)
            digest.update(header)
            remaining = size - len(header)
            while remaining:
                chunk = b"Z" * min(65536, remaining)
                body.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            body.write(b"\r\n")
            # Match browser form ordering: the CSRF token follows the video.
            for key, value in (("permission", "granted"),
                               ("provenance", "synthetic HTTP fixture"),
                               ("camera", ""), ("csrf", self.server.csrf_token)):
                body.write((f'--{boundary}\r\nContent-Disposition: form-data; '
                            f'name="{key}"\r\n\r\n{value}\r\n').encode())
            body.write(f'--{boundary}--\r\n'.encode())
            length = body.tell()
            body.seek(0)
            response = self.request(
                "POST", "/upload", body,
                f"multipart/form-data; boundary={boundary}",
                headers={"Content-Length": str(length)},
            )
        return response, digest.hexdigest()

    def test_exact_150_mib_file_upload_preserves_hash_with_bounded_allocations(self):
        tracemalloc.start()
        try:
            (code, headers, _), digest = self.send_video(150 * 1024 * 1024)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        records = list_clips(self.db, show_paths=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(_stream_sha256(Path(records[0]["source_path"])), digest)
        self.assertLess(peak, 16 * 1024 * 1024)

    def test_file_one_byte_over_limit_is_413_without_registration(self):
        (code, _, _), _ = self.send_video(150 * 1024 * 1024 + 1)
        self.assertEqual(code, 413)
        self.assertEqual(list_clips(self.db), [])
        self.assertFalse(self.uploads.exists() and any(self.uploads.iterdir()))

    def test_avi_larger_than_signature_prefix_remains_supported(self):
        size = 8192
        header = b"RIFF" + (size - 8).to_bytes(4, "little") + b"AVI "
        (code, _, _), _ = self.send_video(size, filename="synthetic.avi", header=header)
        self.assertEqual(code, 303)

    def test_upload_status_is_logged_without_private_fields(self):
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.assertEqual(self.upload(provenance="private provenance")[0], 303)
        self.assertIn("StrokeSense upload: HTTP 303", log.getvalue())
        self.assertNotIn("private provenance", log.getvalue())
        self.assertNotIn(str(self.root), log.getvalue())


if __name__ == "__main__":
    unittest.main()
