"""Tests-first durable withheld-coaching state; synthetic offline jobs only.

A missing-state failure is expected until the job persistence change exists.
No provider calls, athlete footage, cue approval or measured accuracy here.
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


class CoachingJobStateTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.video = self.root / "synthetic.mov"
        self.video.write_bytes(b"synthetic placeholder only")
        self.db = self.root / "registry.sqlite3"
        self.job_db = self.root / "jobs.sqlite3"
        self.results = self.root / "results"
        self.clip_id = register_clip(
            self.video, self.db, permission="granted",
            provenance="offline test-only claim",
        )[0]["clip_id"]

    def make_queue(self, *, succeeds=True):
        def fake(video, *, out_dir):
            if not succeeds:
                return None
            report = Path(out_dir) / "fixture" / "report.html"
            report.parent.mkdir(parents=True)
            report.write_text("<h1>Synthetic only</h1>", encoding="utf-8")
            return {"report": report}
        return JobQueue(
            registry_db=self.db, job_db=self.job_db,
            results_root=self.results, analyze_fn=fake,
        )

    def test_successful_job_stays_explicitly_withheld_after_restart(self):
        with self.make_queue() as q:
            job_id = q.submit(self.clip_id)["job_id"]
            completed = q.wait(job_id, timeout=5)
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(completed["coaching_state"], "withheld")
        with self.make_queue() as q:
            reopened = q.get(job_id)
            self.assertEqual(reopened["coaching_state"], "withheld")
            self.assertEqual(q.list_recent()[0]["coaching_state"], "withheld")

    def test_versioned_withholding_metadata_survives_job_restart(self):
        # Regression for #36: schema version is durable, not a UI-only label.
        with self.make_queue() as queue:
            job_id = queue.submit(self.clip_id)["job_id"]
            done = queue.wait(job_id, timeout=5)
            self.assertEqual(done["coaching_state"], "withheld")
            self.assertEqual(done["coaching_schema_version"], 1)
            self.assertEqual(queue.list_recent()[0]["coaching_schema_version"], 1)
        with self.make_queue() as reopened:
            self.assertEqual(reopened.get(job_id)["coaching_schema_version"], 1)
        import sqlite3
        with sqlite3.connect(self.job_db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
            record = db.execute(
                "SELECT coaching_schema_version FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            self.assertEqual(record, (1,))

    def test_failed_job_does_not_suggest_coaching_release(self):
        with self.make_queue(succeeds=False) as q:
            job_id = q.submit(self.clip_id)["job_id"]
            completed = q.wait(job_id, timeout=5)
            self.assertEqual(completed["status"], "failed")
            self.assertEqual(completed["coaching_state"], "withheld")
            self.assertIsNone(completed["report_path"])

    def test_status_api_exposes_only_safe_withholding(self):
        with self.make_queue() as q:
            job_id = q.submit(self.clip_id)["job_id"]
            self.assertEqual(q.wait(job_id, timeout=5)["status"], "succeeded")
            with create_server(q, registry_db=self.db, port=0) as server:
                thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.01}, daemon=True,
                )
                thread.start()
                try:
                    conn = http.client.HTTPConnection(
                        "127.0.0.1", server.server_address[1], timeout=4,
                    )
                    conn.request("GET", "/api/jobs/" + job_id)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read())
                    conn.close()
                    self.assertEqual(payload["coaching_state"], "withheld")
                    self.assertNotIn(str(self.video), json.dumps(payload))
                    self.assertNotIn("offline test-only claim", json.dumps(payload))
                finally:
                    server.shutdown()
                    thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
