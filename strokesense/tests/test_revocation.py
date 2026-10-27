"""Permission-withdrawal regression tests: synthetic bytes and fake analysis only.

These tests do not verify actual athlete consent or delete prior private results.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import registry
from strokesense.jobs import JobQueue, JobError


class PermissionWithdrawalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.video = self.root / "private-crew.mov"
        self.video.write_bytes(b"synthetic fake footage: not decodable")
        self.registry_db = self.root / "private-registry.sqlite3"
        self.jobs_db = self.root / "jobs.sqlite3"
        self.results = self.root / "results"
        self.provenance = "private-test-consent-reference-123"
        self.clip, _ = registry.register_clip(
            self.video, self.registry_db, permission="granted",
            provenance=self.provenance, group_id="synthetic-session",
            split="development",
        )
        self.clip_id = self.clip["clip_id"]

    def _direct_revoke(self):
        # Baseline missing-behavior test; updates the existing SQLite permission
        # to expose failures in workers that never recheck after submit.
        with sqlite3.connect(self.registry_db) as db:
            db.execute("UPDATE clips SET permission='denied' WHERE clip_id=?",
                       (self.clip_id,))

    def _fake_analyze(self, video, *, out_dir):
        self.assertEqual(Path(video), self.video)
        report = Path(out_dir) / "rendered" / "report.html"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("<h1>Synthetic output, not real footage</h1>",
                          encoding="utf-8")
        return {"report": report}

    def _queue(self, fn):
        return JobQueue(
            registry_db=self.registry_db, job_db=self.jobs_db,
            results_root=self.results, analyze_fn=fn,
        )

    def test_revoke_is_idempotent_and_preserves_original_metadata(self):
        before = registry.list_clips(self.registry_db, show_paths=True)[0]
        first = registry.revoke_clip(self.clip_id, self.registry_db)
        again = registry.revoke_clip(self.clip_id, self.registry_db)
        self.assertEqual(first, again)
        self.assertEqual(first["permission"], "denied")
        self.assertNotIn("source_path", json.dumps(first))
        self.assertNotIn(self.provenance, json.dumps(first))
        after = registry.list_clips(self.registry_db, show_paths=True)[0]
        for key in ("clip_id", "sha256", "size_bytes", "group_id", "split",
                    "source_path", "provenance", "created_utc"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["permission"], "denied")

    def test_unknown_and_malformed_revocation_does_not_create_database(self):
        missing = self.root / "absent.sqlite3"
        with self.assertRaises(registry.RegistryError):
            registry.revoke_clip("f" * 64, missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(registry.RegistryError):
            registry.revoke_clip("../../secret", self.registry_db)
        self.assertEqual(len(registry.list_clips(self.registry_db)), 1)
        self.assertEqual(registry.list_clips(self.registry_db)[0]["permission"],
                         "granted")

    def test_cli_revoke_outputs_only_safe_json_and_rejects_followup_job(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(registry.main(
                ["revoke", self.clip_id, "--db", str(self.registry_db)]
            ), 0)
        payload = stdout.getvalue()
        self.assertNotIn(str(self.video), payload)
        self.assertNotIn(self.provenance, payload)
        self.assertEqual(json.loads(payload)["record"]["permission"], "denied")
        with self._queue(self._fake_analyze) as queue:
            with self.assertRaises(JobError):
                queue.submit(self.clip_id)

    def test_permission_withdrawn_during_analysis_never_publishes_report(self):
        def revoke_during_run(video, *, out_dir):
            result = self._fake_analyze(video, out_dir=out_dir)
            self._direct_revoke()
            return result

        with self._queue(revoke_during_run) as queue:
            start = queue.submit(self.clip_id)
            completed = queue.wait(start["job_id"], timeout=5)
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["error_code"], "permission_revoked")
        self.assertIsNone(completed["report_path"])

    def test_queued_clip_revoked_before_execution_never_runs_analyzer(self):
        entered = threading.Event()
        release = threading.Event()
        seen = Mock()

        def blocked(video, *, out_dir):
            seen(video)
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return self._fake_analyze(video, out_dir=out_dir)

        with self._queue(blocked) as queue:
            first = queue.submit(self.clip_id)
            self.assertTrue(entered.wait(timeout=5))
            queued = queue.submit(self.clip_id)
            self._direct_revoke()
            release.set()
            one = queue.wait(first["job_id"], timeout=5)
            two = queue.wait(queued["job_id"], timeout=5)
        for result in (one, two):
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_code"], "permission_revoked")
            self.assertIsNone(result["report_path"])
        self.assertEqual(seen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
