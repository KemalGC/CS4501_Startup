"""Offline HTTP vertical-slice tests: fabricated container bytes and fake analyzer.

No customer media, ONNX pose model, external LLM, or reviewed coaching cues.
Tests exercise private upload -> queued job -> report/evidence and error paths.
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.evidence import build_evidence_snapshot
from strokesense.jobs import JobError, JobQueue
from strokesense.media import UndecodableMediaError
from strokesense.registry import list_clips
from strokesense.strokes import FAULTS
from strokesense.web import create_server
from test_upload import multipart, SYNTHETIC_MP4


def _mock_evidence():
    """Plausible *synthetic* stroke records; no empirical rower observations."""
    code = next(iter(FAULTS))
    strokes = [
        {"idx": 0, "catch": 1, "finish": 5, "next_catch": 10,
         "faults": [code]},
        {"idx": 1, "catch": 11, "finish": 16, "next_catch": 21,
         "faults": []},
        {"idx": 2, "catch": 22, "finish": 27, "next_catch": 32,
         "faults": []},
    ]
    return build_evidence_snapshot(
        {"rowers": [{"seat": "synthetic-seat", "track": 1,
                     "strokes": strokes}]},
        analysis_key="synthetic-browser-fixture", fps=15.0,
    )


class UploadAndAnalyzeFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry_db = self.root / "registry.sqlite3"
        self.jobs_db = self.root / "jobs.sqlite3"
        self.results = self.root / "results"
        self.upload_dir = self.root / "private"
        self.calls = []
        self.reject_media = False

        def fake_analysis(video, *, out_dir):
            self.calls.append(Path(video))
            if self.reject_media:
                raise UndecodableMediaError("invalid_media")
            output = Path(out_dir) / "mock"
            output.mkdir(parents=True)
            report = output / "report.html"
            report.write_text(
                "<!doctype html><h1>SYNTHETIC fake analyzer report</h1>",
                encoding="utf-8",
            )
            (output / "metrics.json").write_text(
                json.dumps({"evidence": _mock_evidence()}), encoding="utf-8"
            )
            return {"report": report}

        self.worker = JobQueue(
            registry_db=self.registry_db, job_db=self.jobs_db,
            results_root=self.results, analyze_fn=fake_analysis,
        )
        self.addCleanup(self.worker.close)
        self.server = create_server(
            self.worker, registry_db=self.registry_db,
            upload_dir=self.upload_dir, port=0,
        )
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._shutdown)
        self.port = self.server.server_address[1]

    def _shutdown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method, path, *, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        response = (reply.status, dict(reply.getheaders()), reply.read())
        conn.close()
        return response

    def upload(self, *, analyze=False, extra=(), csrf=None, headers=None):
        fields = tuple(extra)
        if analyze:
            fields += (("analyze", "now"),)
        payload, mime = multipart(
            self.server.csrf_token if csrf is None else csrf,
            filename="private-crew.mp4", data=SYNTHETIC_MP4, extras=fields,
        )
        request_headers = {"Content-Type": mime, **(headers or {})}
        return self.request("POST", "/upload", body=payload,
                            headers=request_headers)

    def test_homepage_offers_opt_in_analyze_checkbox(self):
        code, _, body = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'name="analyze"', body)
        self.assertIn(b'value="now"', body)

    def test_single_upload_runs_fake_job_then_shows_report_and_withheld_evidence(self):
        code, headers, _ = self.upload(analyze=True)
        self.assertEqual(code, 303)
        url = headers["Location"]
        self.assertRegex(url, r"^/jobs/[a-f0-9]{32}$")
        job_id = url.rsplit("/", 1)[-1]
        final = self.worker.wait(job_id, timeout=4)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(len(self.calls), 1)
        clips = list_clips(self.registry_db, show_paths=True)
        self.assertEqual(final["clip_id"], clips[0]["clip_id"])
        self.assertEqual(self.calls[0], Path(clips[0]["source_path"]))

        status, _, page = self.request("GET", url)
        self.assertEqual(status, 200)
        self.assertIn(("/reports/" + job_id).encode(), page)
        status, _, report = self.request("GET", "/reports/" + job_id)
        self.assertEqual(status, 200)
        self.assertIn(b"SYNTHETIC fake analyzer", report)
        status, _, payload = self.request(
            "GET", "/api/jobs/" + job_id + "/evidence"
        )
        self.assertEqual(status, 200)
        document = json.loads(payload)
        self.assertEqual(document["coaching_state"], "withheld")
        self.assertEqual(len(document["evidence"]["strokes"]), 3)
        self.assertEqual(len(document["evidence"]["findings"]), 1)
        self.assertNotIn(str(self.root), payload.decode())
        status, _, page = self.request(
            "GET", "/jobs/" + job_id + "/evidence"
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Generated coaching withheld", page)

    def test_register_only_upload_keeps_existing_behavior(self):
        code, headers, _ = self.upload()
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertEqual(len(list_clips(self.registry_db)), 1)
        self.assertEqual(self.worker.list_recent(), [])
        self.assertEqual(self.calls, [])

    def test_duplicate_content_can_opt_into_analysis_without_duplicate_storage(self):
        self.assertEqual(self.upload()[0], 303)
        code, headers, _ = self.upload(analyze=True)
        self.assertEqual(code, 303)
        self.assertRegex(headers["Location"], r"^/jobs/[a-f0-9]{32}$")
        job_id = headers["Location"].split("/")[-1]
        self.assertEqual(self.worker.wait(job_id, timeout=4)["status"],
                         "succeeded")
        self.assertEqual(len(list_clips(self.registry_db)), 1)
        self.assertEqual(len(list(self.upload_dir.iterdir())), 1)

    def test_invalid_analyze_options_fail_closed_before_writes(self):
        for extras in (
            (("analyze", "maybe"),),
            (("analyze", "now"), ("analyze", "now")),
        ):
            with self.subTest(extras=extras):
                code, _, _ = self.upload(extra=extras)
                self.assertEqual(code, 400)
        self.assertEqual(list_clips(self.registry_db), [])
        self.assertEqual(self.worker.list_recent(), [])
        self.assertFalse(self.upload_dir.exists() and
                         any(self.upload_dir.iterdir()))

    def test_failed_analyzer_never_exposes_report_or_private_path(self):
        self.reject_media = True
        code, headers, _ = self.upload(analyze=True)
        self.assertEqual(code, 303)
        job_id = headers["Location"].split("/")[-1]
        self.assertEqual(self.worker.wait(job_id, timeout=4)["status"], "failed")
        code, _, payload = self.request("GET", "/api/jobs/" + job_id)
        self.assertEqual(code, 200)
        record = json.loads(payload)
        self.assertEqual(record["error_code"], "invalid_media")
        self.assertIsNone(record["report_path"])
        self.assertNotIn(str(self.root), payload.decode())
        self.assertEqual(
            self.request("GET", "/reports/" + job_id)[0], 404
        )

    def test_full_queue_does_not_falsely_report_success_and_upload_is_retriable(self):
        with patch.object(self.worker, "submit",
                          side_effect=JobError("queue_full")):
            code, _, body = self.upload(analyze=True)
        self.assertEqual(code, 503)
        self.assertNotIn(str(self.root).encode(), body)
        self.assertEqual(len(list_clips(self.registry_db)), 1)
        self.assertEqual(self.worker.list_recent(), [])
        self.assertEqual(len(list(self.upload_dir.iterdir())), 1)

    def test_forged_opt_in_cannot_bypass_csrf_and_origin(self):
        self.assertEqual(self.upload(analyze=True, csrf="wrong")[0], 403)
        self.assertEqual(self.upload(
            analyze=True, headers={"Origin": "https://evil.invalid"}
        )[0], 403)
        self.assertEqual(list_clips(self.registry_db), [])
        self.assertEqual(self.worker.list_recent(), [])


if __name__ == "__main__":
    unittest.main()
