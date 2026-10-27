"""Deterministic local analysis job lifecycle tests (no model/video inference)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.registry import register_clip


class LocalJobsTests(unittest.TestCase):
    def setUp(self):
        from strokesense.jobs import JobQueue
        self.JobQueue = JobQueue
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clip = self.root / "private-session.mov"
        self.clip.write_bytes(b"synthetic video fixture - not decodable media")
        self.registry_db = self.root / "registry.sqlite3"
        self.jobs_db = self.root / "jobs.sqlite3"
        self.out_dir = self.root / "results"
        self.clip_id = register_clip(
            self.clip, self.registry_db, permission="granted",
            provenance="synthetic test operator claim", group_id="fixture-session",
        )[0]["clip_id"]
        self.calls = Mock(side_effect=self.fake_runner)

    def fake_runner(self, video, *, out_dir):
        self.assertEqual(Path(video), self.clip)
        out = Path(out_dir) / "report-output"
        out.mkdir(parents=True, exist_ok=True)
        report = out / "report.html"
        report.write_text("<h1>synthetic report</h1>", encoding="utf-8")
        return {"report": report}

    def queue(self, **kwargs):
        return self.JobQueue(
            registry_db=self.registry_db, job_db=self.jobs_db,
            results_root=self.out_dir, analyze_fn=self.calls, **kwargs,
        )

    def test_job_completes_with_private_scoped_result_and_durable_status(self):
        with self.queue() as manager:
            queued = manager.submit(self.clip_id)
            self.assertEqual(queued["status"], "queued")
            job_id = queued["job_id"]
            self.assertNotIn(str(self.clip), json.dumps(queued))
            finished = manager.wait(job_id, timeout=5)
            self.assertEqual(finished["status"], "succeeded")
            self.assertTrue(finished["report_path"].endswith("/report.html"))
            self.assertFalse(Path(finished["report_path"]).is_absolute())
            self.assertIn(job_id, finished["report_path"])
            self.assertNotIn(str(self.root), json.dumps(finished))
            self.assertEqual(self.calls.call_count, 1)
        with self.queue() as again:
            self.assertEqual(again.get(job_id)["status"], "succeeded")

    def test_missing_or_unverified_clip_is_rejected_without_enqueuing(self):
        from strokesense.jobs import JobError
        with self.queue() as manager:
            with self.assertRaises(JobError):
                manager.submit("not-a-registered-clip")
        unverified = self.root / "unverified.mov"
        unverified.write_bytes(b"other synthetic fixture")
        other = register_clip(unverified, self.registry_db)[0]["clip_id"]
        with self.queue() as manager:
            with self.assertRaises(JobError):
                manager.submit(other)
        self.calls.assert_not_called()

    def test_source_replacement_after_registration_fails_closed(self):
        self.clip.write_bytes(b"modified synthetic video fixture, still no real video")
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "source_changed")
        self.calls.assert_not_called()

    def test_runner_exception_is_sanitized_and_not_retried(self):
        self.calls.side_effect = RuntimeError("secret name /private/path token")
        with self.queue() as manager:
            started = manager.submit(self.clip_id)
            finished = manager.wait(started["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "analysis_failed")
        self.assertNotIn("secret", json.dumps(finished))
        self.assertNotIn(str(self.clip), json.dumps(finished))
        self.assertEqual(self.calls.call_count, 1)

    def test_no_rowing_motion_results_in_specific_failure(self):
        self.calls.side_effect = lambda *args, **kwargs: None
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "no_rowing_detected")

    def test_report_outside_job_root_is_never_published(self):
        outside = self.root / "private" / "report.html"
        outside.parent.mkdir()
        outside.write_text("not permitted")
        self.calls.side_effect = lambda *args, **kwargs: {"report": outside}
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "invalid_report_location")
        self.assertIsNone(finished["report_path"])

    def test_capacity_limit_rejects_second_job_during_running_first(self):
        from strokesense.jobs import JobError
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return self.fake_runner(*args, **kwargs)
        self.calls.side_effect = slow
        with self.queue(max_pending=1) as manager:
            first = manager.submit(self.clip_id)
            self.assertTrue(entered.wait(timeout=3))
            with self.assertRaises(JobError):
                manager.submit(self.clip_id)
            release.set()
            self.assertEqual(manager.wait(first["job_id"], timeout=5)["status"], "succeeded")


    def test_output_directory_failure_returns_safe_failed_status(self):
        with self.queue() as manager:
            with patch("strokesense.jobs.Path.mkdir",
                       side_effect=OSError("secret absolute filesystem path")):
                record = manager.submit(self.clip_id)
                finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "output_unavailable")
        self.assertNotIn("secret", json.dumps(finished))
        self.calls.assert_not_called()

    def test_unknown_status_id_does_not_expose_records(self):
        with self.queue() as manager:
            self.assertIsNone(manager.get("unknown-id"))
            self.assertIsNone(manager.get("../../private-session.mov"))
            self.assertIsNone(manager.get(""))
            with self.assertRaises(ValueError):
                manager.wait("unknown-id", timeout=1)


if __name__ == "__main__":
    unittest.main()
