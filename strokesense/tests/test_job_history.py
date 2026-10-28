"""Regression tests for a bounded, persistent, privacy-safe job history."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


class JobHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "private-crew.mp4"
        self.source.write_bytes(b"synthetic non-video bytes")
        self.registry = self.root / "registry.sqlite3"
        self.jobs_db = self.root / "jobs.sqlite3"
        self.results = self.root / "output"
        self.clip_id = register_clip(
            self.source, self.registry, permission="granted",
            provenance="test-only fake consent statement"
        )[0]["clip_id"]

        def fake(video, *, out_dir):
            dest = Path(out_dir) / "subdir" / "report.html"
            dest.parent.mkdir(parents=True)
            dest.write_text("<h1>test report</h1>")
            return {"report": dest}

        self.worker = JobQueue(registry_db=self.registry,
                               job_db=self.jobs_db,
                               results_root=self.results, analyze_fn=fake)
        self.addCleanup(self.worker.close)
        self.server = create_server(self.worker, registry_db=self.registry, port=0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever,
                                  kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), thread.join(timeout=3)))
        self.port = self.server.server_address[1]

    def get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request("GET", path, headers=headers or {})
        response = c.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        c.close()
        return result

    def finish(self):
        row = self.worker.submit(self.clip_id)
        self.assertEqual(self.worker.wait(row["job_id"], timeout=4)["status"],
                         "succeeded")
        return row["job_id"]

    def test_empty_history_is_list(self):
        self.assertEqual(self.worker.list_recent(), [])

    def test_latest_first_limit_and_public_projection(self):
        ids = [self.finish() for _ in range(3)]
        records = self.worker.list_recent(limit=2)
        self.assertEqual([r["job_id"] for r in records], ids[-1:-3:-1])
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["status"] == "succeeded" for r in records))
        self.assertNotIn(str(self.root), json.dumps(records))
        self.assertNotIn("fake consent", json.dumps(records))

    def test_limit_must_be_strict_small_integer(self):
        for limit in (0, -1, 101, True, "1", 1.2, None):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.worker.list_recent(limit=limit)
        self.assertEqual(self.worker.list_recent(limit=1), [])

    def test_completed_history_survives_worker_restart(self):
        job_id = self.finish()
        self.worker.close()
        with JobQueue(registry_db=self.registry, job_db=self.jobs_db,
                      results_root=self.results,
                      analyze_fn=lambda *a, **k: None) as restarted:
            rows = restarted.list_recent()
            self.assertEqual(rows[0]["job_id"], job_id)
            self.assertEqual(rows[0]["status"], "succeeded")
            self.assertTrue(rows[0]["report_path"].endswith("report.html"))

    def test_homepage_shows_reopenable_jobs_without_paths(self):
        job_id = self.finish()
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("/jobs/" + job_id, html)
        self.assertIn("succeeded", html)
        self.assertNotIn(str(self.source), html)
        self.assertNotIn("fake consent", html)
        status, _, status_page = self.get("/jobs/" + job_id)
        self.assertEqual(status, 200)
        self.assertIn("/reports/" + job_id, status_page.decode())

    def test_history_json_endpoint_has_bounded_public_records(self):
        job_id = self.finish()
        status, headers, body = self.get("/api/jobs")
        self.assertEqual(status, 200)
        items = json.loads(body)
        self.assertEqual(items[0]["job_id"], job_id)
        self.assertNotIn(str(self.root), body.decode())
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Access-Control-Allow-Origin"] if
                         "Access-Control-Allow-Origin" in headers else None, None)

    def test_history_host_restrictions_still_apply(self):
        self.finish()
        status, _, body = self.get("/api/jobs", headers={"Host":"evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn(str(self.root), body.decode())


    def test_homepage_camera_filter_preserves_jobs_but_scopes_recent_list(self):
        with __import__("sqlite3").connect(self.registry) as db:
            db.execute("UPDATE clips SET camera='side-on' WHERE clip_id=?",
                       (self.clip_id,))
        other_video = self.root / "other-private-crew.mp4"
        other_video.write_bytes(b"different synthetic non-video bytes")
        other_clip = register_clip(
            other_video, self.registry, permission="granted",
            provenance="another test-only claim", camera="bow-on",
        )[0]["clip_id"]
        first = self.finish()
        another_job = self.worker.submit(other_clip)["job_id"]
        self.assertEqual(self.worker.wait(another_job, timeout=4)["status"],
                         "succeeded")
        status, _, base = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(("/jobs/" + first).encode(), base)
        self.assertIn(("/jobs/" + another_job).encode(), base)
        self.assertIn(b'<form method="get" action="/">', base)

        code, _, side = self.get("/?camera=side-on")
        self.assertEqual(code, 200)
        self.assertIn(("/jobs/" + first).encode(), side)
        self.assertNotIn(("/jobs/" + another_job).encode(), side)
        code, _, bow = self.get("/?camera=bow-on")
        self.assertEqual(code, 200)
        self.assertIn(("/jobs/" + another_job).encode(), bow)
        self.assertNotIn(("/jobs/" + first).encode(), bow)
        code, _, unspecified = self.get("/?camera=unspecified")
        self.assertEqual(code, 200)
        self.assertNotIn(("/jobs/" + first).encode(), unspecified)
        self.assertNotIn(("/jobs/" + another_job).encode(), unspecified)
        self.assertNotIn(str(other_video).encode(), side + bow)
        self.assertNotIn(b"another test-only claim", side + bow)

    def test_camera_filter_rejects_unknown_and_duplicate_query_values(self):
        for path in ("/?camera=diagonal",
                     "/?camera=bow-on&camera=side-on",
                     "/?camera=side-on&unused=1"):
            with self.subTest(path=path):
                code, headers, body = self.get(path)
                self.assertEqual(code, 400)
                self.assertIn("no-store", headers["Cache-Control"])
                self.assertNotIn(str(self.root).encode(), body)



    def test_status_filter_and_camera_compose_without_mutating_jobs(self):
        import sqlite3
        with sqlite3.connect(self.registry) as db:
            db.execute("UPDATE clips SET camera='side-on' WHERE clip_id=?",
                       (self.clip_id,))
        other = self.root / "different-view.mp4"
        other.write_bytes(b"mock footage for bow-on")
        second_clip = register_clip(
            other, self.registry, permission="granted",
            provenance="synthetic operator claim", camera="bow-on",
        )[0]["clip_id"]
        side_ok = self.finish()
        side_failed = self.finish()
        bow_failed = self.worker.submit(second_clip)["job_id"]
        self.assertEqual(self.worker.wait(bow_failed, timeout=4)["status"],
                         "succeeded")
        with sqlite3.connect(self.jobs_db) as db:
            db.execute("UPDATE jobs SET status='failed', error_code='analysis_failed' "
                       "WHERE job_id IN (?, ?)", (side_failed, bow_failed))

        code, _, all_jobs = self.get("/?status=")
        self.assertEqual(code, 200)
        for job_id in (side_ok, side_failed, bow_failed):
            self.assertIn(("/jobs/" + job_id).encode(), all_jobs)
        self.assertIn(b'<select name="status">', all_jobs)

        code, _, failed = self.get("/?status=failed")
        self.assertEqual(code, 200)
        self.assertIn(("/jobs/" + side_failed).encode(), failed)
        self.assertIn(("/jobs/" + bow_failed).encode(), failed)
        self.assertNotIn(("/jobs/" + side_ok).encode(), failed)

        code, _, combined = self.get("/?camera=side-on&status=failed")
        self.assertEqual(code, 200)
        self.assertIn(("/jobs/" + side_failed).encode(), combined)
        self.assertNotIn(("/jobs/" + bow_failed).encode(), combined)
        self.assertNotIn(("/jobs/" + side_ok).encode(), combined)
        # Status filter must not change available registered clips or the API.
        self.assertIn(self.clip_id.encode(), combined)
        self.assertIn(second_clip.encode(), combined)
        code, _, api = self.get("/api/jobs")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(api)), 3)
        self.assertNotIn(str(self.root).encode(), combined)

    def test_status_filter_rejects_untrusted_or_repeated_queries(self):
        for path in ("/?status=done", "/?status=failed&status=succeeded",
                     "/?camera=side-on&status=failed&extra=x",
                     "/?status=failed&camera=side-on&camera=bow-on"):
            with self.subTest(path=path):
                code, headers, body = self.get(path)
                self.assertEqual(code, 400)
                self.assertIn("no-store", headers["Cache-Control"])
                self.assertNotIn(str(self.root).encode(), body)

    def test_status_filter_no_matches_is_clear_and_reversible(self):
        done = self.finish()
        code, _, empty = self.get("/?status=failed")
        self.assertEqual(code, 200)
        self.assertIn(b"None yet.", empty)
        self.assertNotIn(("/jobs/" + done).encode(), empty)
        code, _, restored = self.get("/?status=succeeded")
        self.assertEqual(code, 200)
        self.assertIn(("/jobs/" + done).encode(), restored)



if __name__ == "__main__":
    unittest.main()
