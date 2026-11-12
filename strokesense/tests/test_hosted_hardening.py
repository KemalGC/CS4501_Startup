"""Offline security contracts for the public analyzer: no pose model required."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import cli
from strokesense.hosted_demo_state import HostedDemoState
from strokesense.media import probe_decodable_video
from strokesense.web_demo_hosted import VISITOR_UPLOAD_TTL, create_app

FAKE_MP4 = bytes.fromhex("000000186674797069736f6d0000000069736f6d69736f32")
OWNER = "temporary-test-owner-key-" + "x" * 32
ORIGIN = "https://stroke.test"


def _app(root):
    return create_app(
        data_dir=root, origin=ORIGIN, owner_key=OWNER,
        command_factory=lambda: [sys.executable, "-c", "import time;time.sleep(30)"])


class HostedHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = _app(self.tmp.name)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.client.__enter__()
        self.csrf = self.app.state.demo_csrf

    def tearDown(self):
        for entry in list(self.app.state.demo_data["uploads"].values()):
            entry["state"].cancel()
            if entry["state"].worker:
                entry["state"].worker.join(timeout=8)
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def upload(self):
        response = self.client.post("/api/demo/videos", content=FAKE_MP4, headers={
            "origin": ORIGIN, "x-demo-csrf": self.csrf,
            "content-type": "video/mp4", "x-demo-filename": "test.mp4"})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_non_ascii_secrets_are_refused_without_a_server_error(self):
        upload = self.upload()
        bad = "éÿ".encode("latin-1")
        base = {"origin": ORIGIN, "content-type": "application/json"}
        for url in ("/api/demo/sessions/" + "a" * 32 + "/analyze", f"/api/demo/videos/{upload['id']}/analyze",
                    f"/api/demo/videos/{upload['id']}/cancel"):
            response = self.client.post(url, content=b"{}", headers={**base, "x-demo-csrf": bad})
            self.assertEqual(response.status_code, 403, url)
        response = self.client.post(
            f"/api/demo/videos/{upload['id']}/cancel", content=b"{}",
            headers={**base, "x-demo-csrf": self.csrf, "x-demo-delete-token": bad})
        self.assertEqual(response.status_code, 403)
        response = self.client.request(
            "DELETE", f"/api/demo/videos/{upload['id']}",
            headers={"origin": ORIGIN, "x-demo-csrf": self.csrf, "x-demo-delete-token": bad})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/owner/demo-video", content=FAKE_MP4, headers={
            "origin": ORIGIN, "content-type": "video/mp4", "authorization": bad})
        self.assertEqual(response.status_code, 403)

    def test_expired_upload_is_deleted_from_disk_without_another_upload(self):
        upload = self.upload()
        entry = self.app.state.demo_data["uploads"][upload["id"]]
        entry["state"].cancel()
        entry["state"].worker.join(timeout=8)
        folder = entry["root"]
        self.assertTrue(folder.is_dir())
        entry["created"] -= VISITOR_UPLOAD_TTL + 5
        self.app.state.demo_last_sweep[0] = -1e12
        self.assertEqual(self.client.get("/demo/bridge").status_code, 200)
        self.assertFalse(folder.exists())
        self.assertNotIn(upload["id"], self.app.state.demo_data["uploads"])
        self.assertEqual(
            self.client.get(f"/demo/videos/{upload['id']}/video").status_code, 404)

    def test_capability_metadata_is_owner_only(self):
        upload = self.upload()
        meta = self.app.state.demo_data["uploads"][upload["id"]]["root"] / "upload.json"
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(meta.stat().st_mode), 0o600)

    def test_browser_policy_headers(self):
        response = self.client.get("/demo/bridge")
        self.assertIn("camera=()", response.headers["permissions-policy"])
        self.assertEqual(response.headers["x-permitted-cross-domain-policies"], "none")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")


class HostedStartupCleanupTests(unittest.TestCase):
    def test_interrupted_uploads_are_reclaimed_on_restart(self):
        with tempfile.TemporaryDirectory() as root:
            visitors = Path(root) / "demo" / "visitor-uploads"
            visitors.mkdir(parents=True)
            partial = visitors / ".upload-abandoned"
            partial.write_bytes(b"x" * 1024)
            orphan = visitors / ("a" * 48)
            orphan.mkdir()
            (orphan / "input.mp4").write_bytes(FAKE_MP4)
            unrelated = visitors / "keep.txt"
            unrelated.write_text("not ours")
            _app(root)
            self.assertFalse(partial.exists())
            self.assertFalse(orphan.exists())
            self.assertTrue(unrelated.exists())


class BoundedMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        import numpy as np
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.tmp.name) / "clip.avi"
        writer = cv2.VideoWriter(str(cls.video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 64))
        if not writer.isOpened():
            raise unittest.SkipTest("no local video encoder")
        for _ in range(30):
            writer.write(np.zeros((64, 96, 3), np.uint8))
        writer.release()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_probe_enforces_duration_and_pixel_bounds(self):
        self.assertTrue(probe_decodable_video(self.video))
        self.assertFalse(probe_decodable_video(self.video, max_seconds=1.0))
        self.assertFalse(probe_decodable_video(self.video, max_pixels=64 * 64))

    def test_cli_refuses_out_of_bounds_media_before_loading_a_model(self):
        with tempfile.TemporaryDirectory() as out, \
                patch.object(cli, "HOSTED_MAX_SECONDS", 1.0), \
                patch.object(cli, "analyse_video", side_effect=AssertionError("must not run")):
            code = cli.main([str(self.video), "--out", out, "--bounded-media"])
        self.assertEqual(code, cli.MEDIA_REJECTED_EXIT)

    def test_cli_refuses_non_video_bytes(self):
        fake = Path(self.tmp.name) / "fake.mp4"
        fake.write_bytes(FAKE_MP4)
        with patch.object(cli, "analyse_video", side_effect=AssertionError("must not run")):
            self.assertEqual(cli.main([str(fake), "--bounded-media"]), cli.MEDIA_REJECTED_EXIT)

    def test_hosted_worker_always_requests_bounded_media(self):
        fake = Path(self.tmp.name) / "input.mp4"
        fake.write_bytes(FAKE_MP4)
        state = HostedDemoState(fake, Path(self.tmp.name) / "outputs")
        command = state._command()
        self.assertIn("--bounded-media", command)
        self.assertIn("--fresh", command)


if __name__ == "__main__":
    unittest.main()
