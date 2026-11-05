"""Visitor uploads must run real hosted jobs without changing the prepared clip.

The subprocess in this suite writes unmistakably synthetic fixture artifacts;
production still uses the unmodified StrokeSense inference command and LLM step.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

from strokesense.hosted_demo_state import HostedDemoState
from strokesense.web_demo_hosted import create_app


ORIGIN = "https://demo.example.test"
OWNER = "owner-" + "A" * 48
MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
PREPARED = MP4_HEADER + b"P" * 128
CUSTOM = MP4_HEADER + b"C" * 128

WORKER = (
    "from pathlib import Path;import sys,json,time;"
    "time.sleep(.16);"
    "out=Path(sys.argv[1])/'synthetic';out.mkdir(parents=True,exist_ok=True);"
    "video=Path(sys.argv[2]).read_bytes();"
    "(out/'report.html').write_text('<h1>SYNTHETIC FIXTURE '+video[-1:].decode()+'</h1>');"
    "(out/'metrics.json').write_text(json.dumps({'rowers':[{'seat':str(i),'strokes':[{},{}]} for i in range(8)],'crew_cadence':{'rate_spm':30.1}}));"
    "(out/'crew_annotated.mp4').write_bytes(video)"
)


class VisitorUploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "demo").mkdir()
        (self.root / "demo" / "prepared.mp4").write_bytes(PREPARED)
        self.env_patch = patch.dict(os.environ, {"STROKESENSE_LLM_FEEDBACK": "0"})
        self.env_patch.start()
        self.command_patch = patch.object(
            HostedDemoState, "_command",
            lambda state: [sys.executable, "-c", WORKER, str(state.root), str(state.video)],
        )
        self.command_patch.start()
        self.app = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER,
                              max_upload_bytes=1024)

    def tearDown(self):
        self.command_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    async def request(self, method, path, *, app=None, body=None, headers=None, csrf=False, origin=False):
        instance = app or self.app
        custom = dict(headers or {})
        if csrf:
            custom["X-Demo-CSRF"] = instance.state.demo_csrf
        if origin:
            custom["Origin"] = ORIGIN
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=instance), base_url=ORIGIN) as client:
            return await client.request(method, path, content=body, headers=custom)

    async def upload(self, data=CUSTOM, name="crew2.mp4", **kw):
        return await self.request(
            "POST", "/api/demo/videos", body=data,
            headers={"Content-Type": "video/mp4", "X-Demo-Filename": name},
            origin=True, csrf=True, **kw,
        )

    async def finished(self, job_id):
        for _ in range(150):
            snapshot = (await self.request("GET", f"/api/demo/videos/{job_id}/status")).json()
            if snapshot["state"] in ("finished", "failed"):
                return snapshot
            await asyncio.sleep(.03)
        self.fail("Synthetic worker did not reach a terminal state")

    async def test_prepared_video_remains_default_and_new_tabs_have_full_analysis(self):
        page = await self.request("GET", "/demo")
        self.assertEqual(page.status_code, 200, page.text)
        for fragment in ('id="prepared-tab"', 'id="clip-file"',
                         'id="clip-tab-list"', "fetch('/api/demo/videos'", "statusEndpoint()"):
            self.assertIn(fragment, page.text)
        self.assertEqual((await self.request("GET", "/demo/video")).content, PREPARED)
        initial = (await self.request("GET", "/api/demo/status")).json()
        self.assertEqual(initial["state"], "ready")

        response = await self.upload(name="Video%202.mp4")
        self.assertEqual(response.status_code, 202, response.text)
        info = response.json()
        self.assertEqual(info["name"], "Video 2.mp4")
        self.assertEqual(len(info["id"]), 48)
        self.assertTrue(info["started"])
        self.assertEqual((await self.request("GET", info["video_url"])).content, CUSTOM)
        report_while_running = await self.request("GET", info["report_url"])
        self.assertEqual(report_while_running.status_code, 404)

        snapshot = await self.finished(info["id"])
        self.assertEqual(snapshot["state"], "finished", snapshot)
        self.assertTrue(snapshot["has_report"])
        self.assertEqual(snapshot["crew_summary"]["candidate_rowers"], 8)
        report = await self.request("GET", info["report_url"])
        self.assertEqual(report.status_code, 200)
        self.assertIn("SYNTHETIC FIXTURE C", report.text)
        self.assertEqual((await self.request("GET", info["annotated_url"])).content, CUSTOM)
        self.assertEqual((await self.request("GET", "/demo/video")).content, PREPARED)
        self.assertEqual((await self.request("GET", "/api/demo/status")).json()["state"], "ready")
        self.assertEqual((await self.request("GET", "/demo/report")).status_code, 404)

        rerun = await self.request("POST", f"/api/demo/videos/{info['id']}/analyze", body=b"{}",
                                   headers={"Content-Type": "application/json"}, origin=True, csrf=True)
        self.assertEqual(rerun.status_code, 202, rerun.text)
        self.assertEqual((await self.finished(info["id"]))["state"], "finished")

    async def test_upload_validation_and_origin_protection(self):
        missing_origin = await self.request("POST", "/api/demo/videos", body=CUSTOM,
            csrf=True, headers={"Content-Type": "video/mp4", "X-Demo-Filename": "clip.mp4"})
        self.assertEqual(missing_origin.status_code, 403)
        missing_csrf = await self.request("POST", "/api/demo/videos", body=CUSTOM,
            origin=True, headers={"Content-Type": "video/mp4", "X-Demo-Filename": "clip.mp4"})
        self.assertEqual(missing_csrf.status_code, 403)
        bad_file = await self.upload(data=b"not video")
        self.assertEqual(bad_file.status_code, 422)
        traversal = await self.upload(name="..%2Fclip.mp4")
        self.assertEqual(traversal.status_code, 415)
        bad_type = await self.upload(name="clip.exe")
        self.assertEqual(bad_type.status_code, 415)
        oversized = await self.upload(data=MP4_HEADER + b"A" * 1100)
        self.assertEqual(oversized.status_code, 413, oversized.text)
        self.assertFalse(list((self.root / "demo" / "visitor-uploads").iterdir()))

    async def test_per_video_reports_remain_separate_and_rerun_requires_csrf(self):
        first = await self.upload()
        self.assertEqual(first.status_code, 202, first.text)
        first_id = first.json()["id"]
        self.assertEqual((await self.finished(first_id))["state"], "finished")

        second = await self.upload(data=MP4_HEADER + b"D" * 128, name="another.mp4")
        self.assertEqual(second.status_code, 202, second.text)
        second_id = second.json()["id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual((await self.finished(second_id))["state"], "finished")

        first_report = await self.request("GET", f"/demo/videos/{first_id}/report")
        second_report = await self.request("GET", f"/demo/videos/{second_id}/report")
        self.assertIn("SYNTHETIC FIXTURE C", first_report.text)
        self.assertIn("SYNTHETIC FIXTURE D", second_report.text)
        self.assertNotEqual(first_report.text, second_report.text)
        self.assertEqual((await self.request("GET", f"/demo/videos/{first_id}/video")).content, CUSTOM)
        self.assertEqual((await self.request("GET", f"/demo/videos/{second_id}/video")).content,
                         MP4_HEADER + b"D" * 128)

        rerun_no_csrf = await self.request("POST", f"/api/demo/videos/{first_id}/analyze",
                        body=b"{}", headers={"Content-Type": "application/json"}, origin=True)
        self.assertEqual(rerun_no_csrf.status_code, 403)
        rerun_no_origin = await self.request("POST", f"/api/demo/videos/{first_id}/analyze",
                        body=b"{}", headers={"Content-Type": "application/json"}, csrf=True)
        self.assertEqual(rerun_no_origin.status_code, 403)
        self.assertEqual((await self.request("GET", "/demo/video")).content, PREPARED)

    async def test_only_one_analysis_at_a_time(self):
        first = await self.upload()
        self.assertEqual(first.status_code, 202, first.text)
        second = await self.upload(name="clip3.mp4")
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["error"], "analysis_in_progress")
        self.assertEqual((await self.finished(first.json()["id"]))["state"], "finished")

    async def test_public_upload_quota_bounds_paid_render_work(self):
        first = await self.upload()
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual((await self.finished(first.json()["id"]))["state"], "finished")
        with patch("strokesense.web_demo_hosted.VISITOR_CLIENT_HOURLY_LIMIT", 1):
            second = await self.upload(name="next.mp4")
        self.assertEqual(second.status_code, 429, second.text)
        self.assertEqual(second.json()["error"], "upload_rate_limited")

    async def test_expired_upload_cannot_be_read_or_rerun(self):
        accepted = await self.upload()
        job_id = accepted.json()["id"]
        self.assertEqual((await self.finished(job_id))["state"], "finished")
        self.app.state.demo_data["uploads"][job_id]["created"] = time.time() - 2 * 3600 - 1
        for url in (f"/api/demo/videos/{job_id}/status", f"/demo/videos/{job_id}/video",
                    f"/demo/videos/{job_id}/report", f"/demo/videos/{job_id}/annotated"):
            response = await self.request("GET", url)
            self.assertEqual(response.status_code, 404, (url, response.text))
        rerun = await self.request("POST", f"/api/demo/videos/{job_id}/analyze", body=b"{}",
                                   headers={"Content-Type": "application/json"}, origin=True, csrf=True)
        self.assertEqual(rerun.status_code, 404, rerun.text)
        self.assertEqual((await self.request("GET", "/demo/video")).content, PREPARED)

    async def test_reports_survive_backend_restart_with_private_ids(self):
        accepted = await self.upload()
        job_id = accepted.json()["id"]
        self.assertEqual((await self.finished(job_id))["state"], "finished")
        restarted = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER)
        status = await self.request("GET", f"/api/demo/videos/{job_id}/status", app=restarted)
        self.assertEqual(status.json()["state"], "finished", status.text)
        report = await self.request("GET", f"/demo/videos/{job_id}/report", app=restarted)
        self.assertEqual(report.status_code, 200)
        self.assertIn("SYNTHETIC FIXTURE C", report.text)
        self.assertEqual((await self.request("GET", "/demo/video", app=restarted)).content, PREPARED)
        self.assertEqual((await self.request("GET", "/demo/videos/" + "0" * 48 + "/report",
            app=restarted)).status_code, 404)


if __name__ == "__main__":
    unittest.main()
