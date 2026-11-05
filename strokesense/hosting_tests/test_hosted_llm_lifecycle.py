"""Hosted feedback lifecycle with synthetic vision artifacts and stub model execution."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import httpx

from strokesense.web_demo_hosted import create_app


ORIGIN = "https://demo.example.test"
OWNER = "owner-" + "A" * 48
VIDEO = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"A" * 128


class HostedLLMLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "demo").mkdir()
        (self.root / "demo" / "prepared.mp4").write_bytes(VIDEO)
        self.apps = []
        self.vision_runs = 0
        self.llm_calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.return_code = 0
        self.force_timeout = False
        self.partial_feedback = False
        self.measured_baselines = {}
        self.status = {"state": "missing"}
        self.completed_status = {"state": "generated", "model": "SYNTHETIC TEST MODEL"}
        module = types.ModuleType("strokesense.llm_feedback")
        module.feedback_status = lambda report: dict(self.status)
        self.restore_measured = Mock(side_effect=self.restore_report)
        module.restore_measured_report = self.restore_measured
        self.module_patch = patch.dict(sys.modules, {"strokesense.llm_feedback": module})
        self.module_patch.start()
        self.env_patch = patch.dict(os.environ, {"STROKESENSE_LLM_FEEDBACK": "1"})
        self.env_patch.start()
        self.real_popen = subprocess.Popen
        self.popen_patch = patch("subprocess.Popen", side_effect=self.popen)
        self.popen_patch.start()
        self.killpg = Mock()
        self.kill_patch = patch("os.killpg", self.killpg)
        self.kill_patch.start()
        self.app = self.new_app()

    def popen(self, command, *args, **kwargs):
        if "strokesense.llm_feedback" not in command:
            return self.real_popen(command, *args, **kwargs)
        self.llm_calls.append((command, kwargs))
        report = Path(command[-1])
        self.measured_baselines.setdefault(report, report.read_bytes())
        owner = self

        class SyntheticProcess:
            pid = 424242
            waits = 0

            def wait(self, timeout):
                self.waits += 1
                owner.started.set()
                if owner.force_timeout and self.waits == 1:
                    raise subprocess.TimeoutExpired(command, timeout)
                if not owner.force_timeout and not owner.release.wait(5):
                    raise subprocess.TimeoutExpired(command, timeout)
                if owner.partial_feedback:
                    report.write_bytes(owner.measured_baselines[report] +
                        b'<div data-strokesense-llm="summary">UNVERIFIED GENERATED TEXT</div>')
                if owner.return_code == 0 and not owner.force_timeout:
                    owner.status = dict(owner.completed_status)
                return owner.return_code

        return SyntheticProcess()

    def restore_report(self, report):
        if report in self.measured_baselines and b"data-strokesense-llm" in report.read_bytes():
            report.write_bytes(self.measured_baselines[report])
            return True
        return False

    def vision_command(self, output_dir):
        self.vision_runs += 1
        source = """
from pathlib import Path
import json,sys
out=Path(sys.argv[1])/'synthetic'
out.mkdir(parents=True,exist_ok=True)
(out/'report.html').write_text('<html><body><h1>TEST MEASUREMENT REPORT</h1></body></html>')
(out/'metrics.json').write_text(json.dumps({'rowers':[{'seat':str(i),'strokes':[{}]*2} for i in range(8)],'crew_cadence':{'rate_spm':30.1}}))
(out/'crew_annotated.mp4').write_bytes(b'TEST MP4')
"""
        return [sys.executable, "-c", source, str(output_dir)]

    def new_app(self):
        app = create_app(
            data_dir=self.root, origin=ORIGIN, owner_key=OWNER,
            command_factory=lambda: self.vision_command(app.state.demo_data["demo"].root),
        )
        self.apps.append(app)
        return app

    async def asyncTearDown(self):
        self.release.set()
        for app in self.apps:
            worker = app.state.demo_data["demo"].worker
            if worker is not None:
                await asyncio.to_thread(worker.join, 5)
        self.kill_patch.stop()
        self.popen_patch.stop()
        self.env_patch.stop()
        self.module_patch.stop()
        self.tmp.cleanup()

    async def request(self, method, path, *, app=None):
        app = app or self.app
        headers = {}
        content = None
        if method == "POST":
            headers = {"Origin": ORIGIN, "X-Demo-CSRF": app.state.demo_csrf,
                       "Content-Type": "application/json"}
            content = b"{}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            return await client.request(method, path, headers=headers, content=content)

    async def join(self, app=None):
        app = app or self.app
        worker = app.state.demo_data["demo"].worker
        if worker is not None:
            await asyncio.to_thread(worker.join, 5)
            self.assertFalse(worker.is_alive(), "Synthetic worker did not finish")

    async def start(self):
        response = await self.request("POST", "/api/demo/analyze")
        self.assertEqual(response.status_code, 202, response.text)

    async def measured_baseline(self):
        # Prepare a previous successful vision-only report, exactly like the
        # existing live report being upgraded on the first LLM deployment.
        os.environ["STROKESENSE_LLM_FEEDBACK"] = "0"
        self.app = self.new_app()
        await self.start()
        await self.join()
        os.environ["STROKESENSE_LLM_FEEDBACK"] = "1"
        report = self.app.state.demo_data["demo"].report
        return report, hashlib.sha256(report.read_bytes()).hexdigest(), self.app.state.demo_data["demo"].run_id

    async def test_new_analysis_waits_for_feedback_and_persists_its_state(self):
        await self.start()
        self.assertTrue(await asyncio.to_thread(self.started.wait, 3))
        response = await self.request("GET", "/api/demo/status")
        status = response.json()
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["llm_feedback"]["state"], "running")
        self.assertFalse(status["has_report"])
        self.assertFalse(status["can_rerun"])
        self.assertEqual((await self.request("GET", "/demo/report")).status_code, 404)
        self.assertEqual((await self.request("POST", "/api/demo/analyze")).status_code, 409)
        self.release.set()
        await self.join()
        status = (await self.request("GET", "/api/demo/status")).json()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["llm_feedback"], self.completed_status)
        self.assertTrue(status["has_report"])
        saved = json.loads((self.root / "demo" / "outputs" / "latest.json").read_text())
        self.assertEqual(saved["llm_feedback"], self.completed_status)

    async def test_failed_feedback_leaves_measured_report_available(self):
        self.return_code = 1
        self.partial_feedback = True
        self.release.set()
        await self.start()
        await self.join()
        status = (await self.request("GET", "/api/demo/status")).json()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["llm_feedback"]["state"], "failed")
        self.assertNotIn("LLM-generated", status["detail"])
        report = await self.request("GET", "/demo/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("TEST MEASUREMENT REPORT", report.text)
        self.assertNotIn("UNVERIFIED GENERATED TEXT", report.text)
        self.assertNotIn("data-strokesense-llm", report.text)
        self.assertEqual(status["crew_summary"]["shared_rate_spm"], 30.1)

    async def test_successful_process_cannot_claim_unvalidated_feedback(self):
        self.completed_status = {"state": "outdated"}
        self.partial_feedback = True
        self.release.set()
        await self.start()
        await self.join()
        status = (await self.request("GET", "/api/demo/status")).json()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["llm_feedback"]["state"], "failed")
        report = await self.request("GET", "/demo/report")
        self.assertEqual(report.status_code, 200)
        self.assertNotIn("UNVERIFIED GENERATED TEXT", report.text)

    async def test_feedback_timeout_kills_model_process_group_and_keeps_report(self):
        self.force_timeout = True
        await self.start()
        await self.join()
        self.assertEqual(len(self.llm_calls), 1)
        self.assertTrue(self.llm_calls[0][1]["start_new_session"])
        self.killpg.assert_called_once()
        self.assertEqual(self.killpg.call_args.args[0], 424242)
        status = (await self.request("GET", "/api/demo/status")).json()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["llm_feedback"]["state"], "failed")
        self.assertTrue(status["has_report"])

    async def test_startup_upgrade_keeps_report_readable_without_repeating_vision(self):
        report, original_hash, run_id = await self.measured_baseline()
        restarted = self.new_app()
        self.assertTrue(await asyncio.to_thread(self.started.wait, 3))
        status = (await self.request("GET", "/api/demo/status", app=restarted)).json()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["llm_feedback"]["state"], "running")
        self.assertEqual(status["run_id"], run_id)
        self.restore_measured.assert_called_once_with(report)
        self.assertFalse(status["can_rerun"])
        self.assertEqual((await self.request("GET", "/demo/report", app=restarted)).status_code, 200)
        self.assertEqual((await self.request("POST", "/api/demo/analyze", app=restarted)).status_code, 409)
        self.release.set()
        await self.join(restarted)
        self.assertEqual(self.vision_runs, 1)
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(), original_hash)

    async def test_current_feedback_is_restored_without_model_or_vision_run(self):
        report, _, run_id = await self.measured_baseline()
        self.status = dict(self.completed_status)
        restarted = self.new_app()
        self.assertIsNone(restarted.state.demo_data["demo"].worker)
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.vision_runs, 1)
        status = (await self.request("GET", "/api/demo/status", app=restarted)).json()
        self.assertEqual(status["run_id"], run_id)
        self.assertEqual(status["llm_feedback"]["state"], "generated")
        self.assertTrue(report.exists())

    async def test_repeated_stale_feedback_upgrades_do_not_prune_saved_report(self):
        report, _, run_id = await self.measured_baseline()
        self.release.set()
        for _ in range(3):
            self.status = {"state": "outdated"}
            restarted = self.new_app()
            await self.join(restarted)
            self.assertTrue(report.exists())
            status = (await self.request("GET", "/api/demo/status", app=restarted)).json()
            self.assertEqual(status["state"], "finished")
            self.assertEqual(status["run_id"], run_id)
            self.assertEqual(status["llm_feedback"]["state"], "generated")
        self.assertEqual(self.vision_runs, 1)
        self.assertEqual(len(self.llm_calls), 3)


if __name__ == "__main__":
    unittest.main()
