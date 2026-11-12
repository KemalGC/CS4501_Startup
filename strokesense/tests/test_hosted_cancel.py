"""Offline visitor upload/cancel contract tests: no actual pose model required."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import quote

import httpx
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.web_demo_hosted import VISITOR_UPLOAD_BYTES, create_app


FAKE_MP4 = bytes.fromhex("000000186674797069736f6d0000000069736f6d69736f32")


class HostedVisitorCancelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.origin = "https://stroke.test"
        self.app = create_app(
            data_dir=self.tmp.name, origin=self.origin,
            owner_key="temporary-test-owner-key-" + "x" * 32,
            command_factory=lambda: [sys.executable, "-c", "import time;time.sleep(30)"],
        )
        self.client = TestClient(self.app, base_url=self.origin)
        self.client.__enter__()
        self.csrf = self.app.state.demo_csrf
        self.uploads = []

    def tearDown(self):
        for item in self.uploads:
            state = self.app.state.demo_data["uploads"].get(item["id"], {}).get("state")
            if state is not None:
                state.cancel()
                if state.worker:
                    state.worker.join(timeout=8)
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def post(self, url, *, headers=None, content=b"{}"):
        return self.client.post(url, content=content, headers={
            "origin": self.origin, "x-demo-csrf": self.csrf, **(headers or {})
        })

    def upload(self, display="Eight test"):
        response = self.post("/api/demo/videos", content=FAKE_MP4,
            headers={"content-type": "video/mp4", "x-demo-filename": "test.mp4",
                     "x-demo-display-name": quote(display)})
        self.assertEqual(response.status_code, 202, response.text)
        upload = response.json()
        self.uploads.append(upload)
        return upload

    def cancel(self, upload, *, token=None):
        return self.post(f"/api/demo/videos/{upload['id']}/cancel",
            headers={"content-type": "application/json",
                     "x-demo-delete-token": token if token is not None
                         else upload["delete_token"]})

    def wait_status(self, upload, expected, timeout=9):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            status = self.client.get(f"/api/demo/videos/{upload['id']}/status").json()
            if status["state"] == expected:
                return status
            time.sleep(.05)
        self.fail(f"status did not reach {expected}: {status}")

    def test_upload_limit_is_100_mib(self):
        self.assertEqual(VISITOR_UPLOAD_BYTES, 100 * 1024 * 1024)

    def test_unsafe_display_names_are_rejected(self):
        for name in ("team\u202eone", "test\u200b", "test\u034f", "bad\nlabel", "../path"):
            with self.subTest(name=repr(name)):
                response = self.post("/api/demo/videos", content=FAKE_MP4,
                    headers={"content-type": "video/mp4", "x-demo-filename": "test.mp4",
                             "x-demo-display-name": quote(name)})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.app.state.demo_data["uploads"], {})

    def test_unsafe_filename_cannot_be_default_display_name(self):
        response = self.post("/api/demo/videos", content=FAKE_MP4,
            headers={"content-type": "video/mp4",
                     "x-demo-filename": quote("team\u202eone.mp4")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.app.state.demo_data["uploads"], {})

    def test_running_cancel_preserves_uploaded_video(self):
        clip = self.upload("Morning 8+")
        self.assertEqual(clip["name"], "Morning 8+")
        state = self.app.state.demo_data["uploads"][clip["id"]]["state"]
        before = time.monotonic()
        while state.process is None and time.monotonic() - before < 3:
            time.sleep(.02)
        self.assertIsNotNone(state.process)
        self.assertEqual(self.cancel(clip, token="wrong-token").status_code, 403)
        response = self.cancel(clip)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["state"], "stopping")
        self.wait_status(clip, "cancelled")
        self.assertTrue(self.app.state.demo_data["uploads"][clip["id"]]["video"].is_file())
        self.assertEqual(state.error, "analysis_cancelled")
        self.assertEqual(self.cancel(clip).json()["state"], "cancelled")

    def test_queued_cancel_is_immediate_and_survives_restart(self):
        first = self.upload("First")
        second = self.upload("Second")
        self.assertTrue(second["queued"])
        response = self.cancel(second)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "cancelled")
        self.assertEqual(self.wait_status(second, "cancelled")["can_rerun"], True)
        entry = self.app.state.demo_data["uploads"][second["id"]]
        self.assertTrue(entry["video"].exists())
        self.assertTrue(json.loads((entry["root"] / "upload.json").read_text())["cancelled"])
        self.cancel(first)
        self.wait_status(first, "cancelled")

        # Fresh app restores the cancelled visitor clip without requeueing it.
        new_app = create_app(data_dir=self.tmp.name, origin=self.origin,
            owner_key="temporary-test-owner-key-" + "x" * 32,
            command_factory=lambda: [sys.executable, "-c", "import time;time.sleep(30)"])
        restored = new_app.state.demo_data["uploads"][second["id"]]
        self.assertFalse(restored["queued"])
        self.assertEqual(restored["name"], "Second")

    def test_cancelled_clip_can_be_reanalysed(self):
        clip = self.upload()
        self.cancel(clip)
        self.wait_status(clip, "cancelled")
        denied = self.post(f"/api/demo/videos/{clip['id']}/analyze",
            headers={"content-type": "application/json"})
        self.assertEqual(denied.status_code, 403)
        restarted = self.post(f"/api/demo/videos/{clip['id']}/analyze",
            headers={"content-type": "application/json", "x-demo-delete-token": clip["delete_token"]})
        self.assertEqual(restarted.status_code, 202, restarted.text)
        self.assertTrue(restarted.json()["started"])
        self.assertIn(self.cancel(clip).status_code, (200, 202))
        self.wait_status(clip, "cancelled")

    def test_analysis_reruns_have_a_rate_limit(self):
        clip = self.upload()
        self.cancel(clip)
        self.wait_status(clip, "cancelled")
        url = f"/api/demo/videos/{clip['id']}/analyze"
        headers = {"content-type": "application/json", "x-demo-delete-token": clip["delete_token"]}
        with patch("strokesense.web_demo_hosted.ANALYSIS_GLOBAL_HOURLY_LIMIT", 1):
            self.assertEqual(self.post(url, headers=headers).status_code, 202)
            self.cancel(clip)
            self.wait_status(clip, "cancelled")
            self.assertEqual(self.post(url, headers=headers).status_code, 429)

    def test_slow_upload_does_not_block_existing_video_deletion(self):
        clip = self.upload()
        self.cancel(clip)
        self.wait_status(clip, "cancelled")

        async def exercise():
            first_chunk_sent = asyncio.Event()
            release_upload = asyncio.Event()

            async def slow_video():
                yield FAKE_MP4[:8]
                first_chunk_sent.set()
                await release_upload.wait()
                yield FAKE_MP4[8:]

            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app), base_url=self.origin) as client:
                upload_task = asyncio.create_task(client.post("/api/demo/videos",
                    content=slow_video(), headers={"origin": self.origin,
                        "x-demo-csrf": self.csrf, "content-type": "video/mp4",
                        "x-demo-filename": "slow.mp4"}))
                await asyncio.wait_for(first_chunk_sent.wait(), timeout=3)
                try:
                    deleted = await asyncio.wait_for(client.delete(
                        f"/api/demo/videos/{clip['id']}", headers={
                            "origin": self.origin, "x-demo-csrf": self.csrf,
                            "x-demo-delete-token": clip["delete_token"]}), timeout=3)
                    self.assertEqual(deleted.status_code, 200, deleted.text)
                finally:
                    release_upload.set()
                response = await asyncio.wait_for(upload_task, timeout=3)
                self.assertEqual(response.status_code, 202, response.text)
                self.uploads.append(response.json())

        asyncio.run(exercise())

    def test_incomplete_control_body_times_out(self):
        async def exercise():
            async def slow_json():
                yield b"{"
                await asyncio.sleep(1)
                yield b"}"

            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app), base_url=self.origin) as client:
                with patch("strokesense.web_demo_hosted.CONTROL_BODY_DEADLINE_SECONDS", .02):
                    response = await client.post("/api/demo/sessions/" + "a" * 32 + "/analyze", content=slow_json(), headers={
                        "origin": self.origin, "x-demo-csrf": self.csrf,
                        "content-type": "application/json"})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"], "expected_empty_json")

        asyncio.run(exercise())

    def test_idle_upload_times_out_and_releases_slot(self):
        async def exercise():
            async def stalled_video():
                yield FAKE_MP4[:8]
                await asyncio.sleep(1)
                yield FAKE_MP4[8:]

            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app), base_url=self.origin) as client:
                with patch("strokesense.web_demo_hosted.UPLOAD_IDLE_SECONDS", .02):
                    response = await client.post("/api/demo/videos", content=stalled_video(),
                        headers={"origin": self.origin, "x-demo-csrf": self.csrf,
                            "content-type": "video/mp4", "x-demo-filename": "slow.mp4"})
                self.assertEqual(response.status_code, 408, response.text)
                self.assertEqual(response.json()["error"], "upload_timed_out")

        asyncio.run(exercise())
        clip = self.upload()
        self.assertTrue(clip["id"])

    def test_csp_nonce_changes_for_each_page(self):
        first = self.client.get("/setup")
        second = self.client.get("/setup")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_csp = first.headers["content-security-policy"]
        second_csp = second.headers["content-security-policy"]
        self.assertNotEqual(first_csp, second_csp)
        self.assertIn(first_csp.split("script-src 'nonce-")[1].split("'")[0], first.text)
        self.assertIn(second_csp.split("script-src 'nonce-")[1].split("'")[0], second.text)


if __name__ == "__main__":
    unittest.main()
