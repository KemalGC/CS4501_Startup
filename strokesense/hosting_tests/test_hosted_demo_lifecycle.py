"""Real-demo lifecycle contracts using explicitly synthetic worker artifacts."""
from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from strokesense.web_demo_hosted import create_app


ORIGIN = "https://demo.example.test"
SOURCE = "https://strokesense-review.kemalgcortuk.chatgpt.site/demo-media/strokesense-demo.mp4"
OWNER = "owner-" + "A" * 48
VALID_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"A" * 128
SHA256 = hashlib.sha256(VALID_MP4).hexdigest()


class DownloadResponse(io.BytesIO):
    def __init__(self, body=VALID_MP4, *, length=None, url=SOURCE):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body) if length is None else length),
                        "Content-Type": "video/mp4"}
        self.status = 200
        self.url = url

    def geturl(self):
        return self.url


class HostedDemoLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workers = []
        self.runs = 0
        self.app = self.new_app()

    def worker_command(self, output_dir):
        self.runs += 1
        code = """
from pathlib import Path
import json,sys,time
out=Path(sys.argv[1])/'synthetic'
out.mkdir(parents=True,exist_ok=True)
time.sleep(0.35)
(out/'report.html').write_text('<h1>TEST FIXTURE ONLY</h1><p>Run '+sys.argv[2]+'</p>')
(out/'metrics.json').write_text(json.dumps({'rowers':[{'seat':str(i),'strokes':[{}]*2} for i in range(8)],'crew_cadence':{'rate_spm':30.1}}))
(out/'crew_annotated.mp4').write_bytes(b'FAKE VIDEO')
"""
        return [sys.executable, "-c", code,
                str(output_dir), str(self.runs)]

    def new_app(self, **kwargs):
        app = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER,
                         max_upload_bytes=1024,
                         command_factory=lambda: self.worker_command(app.state.demo_data['demo'].root),
                         **kwargs)
        return app

    async def asyncTearDown(self):
        if self.runs:
            await self.finished()
        self.tmp.cleanup()

    async def req(self, method, path, *, app=None, owner=False,
                  csrf=False, origin=None, body=None, headers=None):
        app = app or self.app
        hdr = dict(headers or {})
        if owner:
            hdr["Authorization"] = "Bearer " + OWNER
        if csrf:
            hdr["X-Demo-CSRF"] = app.state.demo_csrf
        if origin:
            hdr["Origin"] = origin
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url=ORIGIN) as client:
            return await client.request(method, path, content=body, headers=hdr)

    async def prepare(self):
        response = await self.req("POST", "/api/owner/demo-video", owner=True,
                                  origin=ORIGIN, body=VALID_MP4,
                                  headers={"Content-Type": "video/mp4"})
        self.assertEqual(response.status_code, 201, response.text)

    async def analyze(self, *, app=None):
        return await self.req("POST", "/api/demo/analyze", app=app, csrf=True,
                              origin=ORIGIN, body=b"{}",
                              headers={"Content-Type": "application/json"})

    async def finished(self, *, app=None):
        for _ in range(240):
            response = await self.req("GET", "/api/demo/status", app=app)
            self.assertEqual(response.status_code, 200, response.text)
            snapshot = response.json()
            if snapshot["state"] in ("finished", "failed"):
                self.assertEqual(snapshot["state"], "finished", snapshot)
                return snapshot
            await asyncio.sleep(0.025)
        self.fail("Synthetic analysis did not finish")

    async def completed(self):
        await self.prepare()
        self.assertEqual((await self.analyze()).status_code, 202)
        return await self.finished()

    async def test_finished_report_survives_restart_without_another_run(self):
        first = await self.completed()
        restarted = self.new_app()
        status = await self.req("GET", "/api/demo/status", app=restarted)
        self.assertEqual(status.json()["state"], "finished", status.text)
        self.assertEqual(status.json()["crew_summary"], first["crew_summary"])
        report = await self.req("GET", "/demo/report", app=restarted)
        self.assertEqual(report.status_code, 200)
        self.assertIn("Run 1", report.text)
        self.assertEqual(self.runs, 1)

    async def test_changed_clip_does_not_restore_another_clips_report(self):
        await self.completed()
        (self.root / "demo" / "prepared.mp4").write_bytes(VALID_MP4 + b"changed")
        restarted = self.new_app()
        status = await self.req("GET", "/api/demo/status", app=restarted)
        self.assertEqual(status.json()["state"], "ready", status.text)
        self.assertFalse(status.json()["has_report"])
        self.assertEqual((await self.req("GET", "/demo/report", app=restarted)).status_code, 404)

    async def test_rerun_hides_old_artifacts_and_rejects_a_concurrent_run(self):
        await self.completed()
        self.assertEqual((await self.analyze()).status_code, 202)
        status = await self.req("GET", "/api/demo/status")
        self.assertEqual(status.json()["state"], "running")
        self.assertFalse(status.json()["has_report"])
        self.assertEqual((await self.req("GET", "/demo/report")).status_code, 404)
        self.assertEqual((await self.req("GET", "/demo/annotated")).status_code, 404)
        self.assertEqual((await self.analyze()).status_code, 409)
        await self.finished()
        report = await self.req("GET", "/demo/report")
        self.assertIn("Run 2", report.text)

    async def test_rerun_waits_for_completed_worker_to_finish_saving(self):
        await self.prepare()
        demo = self.app.state.demo_data["demo"]
        demo.phase = "finished"
        demo.worker = Mock()
        demo.worker.is_alive.return_value = True
        self.assertEqual((await self.analyze()).status_code, 409)
        self.assertEqual(self.runs, 0)
        demo.worker = None
        demo.phase = "ready"

    async def test_invalid_saved_metrics_cannot_restore_success(self):
        await self.completed()
        next((self.root / "demo" / "outputs").rglob("metrics.json")).write_text("{}")
        restarted = self.new_app()
        status = await self.req("GET", "/api/demo/status", app=restarted)
        self.assertEqual(status.json()["state"], "ready", status.text)
        self.assertEqual((await self.req("GET", "/demo/report", app=restarted)).status_code, 404)

    async def test_bootstrap_prepares_verified_clip_without_starting_inference(self):
        with patch("urllib.request.urlopen", return_value=DownloadResponse()) as fetch:
            app = self.new_app(bootstrap_url=SOURCE, bootstrap_sha256=SHA256)
            await asyncio.to_thread(app.state.bootstrap_thread.join, 3)
            self.assertFalse(app.state.bootstrap_thread.is_alive())
        self.assertTrue(fetch.called)
        self.assertEqual((self.root / "demo" / "prepared.mp4").read_bytes(), VALID_MP4)
        status = await self.req("GET", "/api/demo/status", app=app)
        self.assertEqual(status.json()["state"], "ready", status.text)
        self.assertEqual(self.runs, 0)
        # A public sample does not grant permission to replace it or upload files.
        denied = await self.req("POST", "/api/owner/demo-video", app=app,
                                origin=ORIGIN, body=VALID_MP4,
                                headers={"Content-Type": "video/mp4"})
        self.assertEqual(denied.status_code, 403)

    async def test_bootstrap_never_replaces_an_existing_uploaded_clip(self):
        await self.prepare()
        with patch("urllib.request.urlopen") as fetch:
            app = self.new_app(bootstrap_url=SOURCE, bootstrap_sha256="0" * 64)
            thread = getattr(app.state, "bootstrap_thread", None)
            if thread is not None:
                await asyncio.to_thread(thread.join, 3)
        fetch.assert_not_called()
        self.assertEqual((self.root / "demo" / "prepared.mp4").read_bytes(), VALID_MP4)


class BootstrapDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = Path(self.tmp.name) / "prepared.mp4"

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, response, *, url=SOURCE, sha256=SHA256, limit=1024):
        from strokesense.web_demo_hosted import _install_demo_video
        with patch("urllib.request.urlopen", return_value=response):
            return _install_demo_video(url, sha256, self.video, limit)

    def test_verified_download_is_published_atomically(self):
        self.install(DownloadResponse())
        self.assertEqual(self.video.read_bytes(), VALID_MP4)
        self.assertEqual(list(self.video.parent.iterdir()), [self.video])

    def test_invalid_hash_length_and_container_leave_no_prepared_file(self):
        cases = [
            (DownloadResponse(), {"sha256": "0" * 64}),
            (DownloadResponse(length=len(VALID_MP4) + 10), {}),
            (DownloadResponse(b"not video"), {"sha256": hashlib.sha256(b"not video").hexdigest()}),
            (DownloadResponse(), {"limit": 32}),
        ]
        for response, kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, OSError)):
                self.install(response, **kwargs)
            self.assertFalse(self.video.exists())
            self.assertFalse(list(self.video.parent.iterdir()))

    def test_bootstrap_fetch_is_limited_to_the_expected_public_sample(self):
        for url in (
            "https://evil.example/demo.mp4",
            "http://strokesense-review.kemalgcortuk.chatgpt.site/demo-media/strokesense-demo.mp4",
            "https://strokesense-review.kemalgcortuk.chatgpt.site/api/private-video",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.install(DownloadResponse(), url=url)
            self.assertFalse(self.video.exists())


if __name__ == "__main__":
    unittest.main()
