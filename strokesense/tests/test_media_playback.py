"""Synthetic browser regression for permission-scoped annotated media playback.

All content is invented bytes, not private footage or a real decoding test.
"""
from __future__ import annotations

import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip, revoke_clip
from strokesense.web import create_server


class SavedMediaPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "private-input.mp4"
        self.source.write_bytes(b"synthetic non-video source")
        self.registry = self.root / "registry.sqlite3"
        self.clip_id = register_clip(
            self.source, self.registry, permission="granted",
            provenance="test-only invented operator assertion",
        )[0]["clip_id"]
        self.media = None

        def fake_analyzer(video, *, out_dir):
            dest = Path(out_dir) / "renders"
            dest.mkdir(parents=True)
            report = dest / "report.html"
            report.write_text("<h1>invented report</h1>")
            self.media = dest / "annotated.mp4"
            self.media.write_bytes(b"synthetic annotated video bytes only")
            return {"report": report, "video": self.media}

        self.worker = JobQueue(
            registry_db=self.registry, job_db=self.root / "jobs.sqlite3",
            results_root=self.root / "results", analyze_fn=fake_analyzer,
        )
        self.addCleanup(self.worker.close)
        self.server = create_server(
            self.worker, registry_db=self.registry, port=0,
        )
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        thread.start()
        self.addCleanup(
            lambda: (self.server.shutdown(), thread.join(timeout=3))
        )
        self.port = self.server.server_address[1]

    def get(self, path, *, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        value = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return value

    def submit(self):
        row = self.worker.submit(self.clip_id)
        done = self.worker.wait(row["job_id"], timeout=4)
        self.assertEqual(done["status"], "succeeded")
        return row["job_id"]

    def test_annotated_media_visible_on_success_and_served_locally(self):
        job_id = self.submit()
        code, _, page = self.get(f"/jobs/{job_id}")
        self.assertEqual(code, 200)
        self.assertIn(b"<video", page)
        self.assertIn(f'/media/{job_id}'.encode(), page)
        self.assertNotIn(str(self.root).encode(), page)
        status, headers, body = self.get(f"/media/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(body, b"synthetic annotated video bytes only")
        self.assertNotIn(str(self.root).encode(), body)
        public = self.worker.get(job_id)
        self.assertNotIn("media_sha256", public)
        self.assertNotIn("video_path", public)

    def test_modified_or_revoked_media_is_never_served(self):
        job_id = self.submit()
        self.media.write_bytes(b"modified synthetic media")
        status, headers, body = self.get(f"/media/{job_id}")
        self.assertEqual(status, 409)
        self.assertNotIn(str(self.root).encode(), body)
        # Restore exact bytes, then withdraw permission.
        self.media.write_bytes(b"synthetic annotated video bytes only")
        revoke_clip(self.clip_id, self.registry)
        status, _, body = self.get(f"/media/{job_id}")
        self.assertEqual(status, 403)
        self.assertNotIn(str(self.root).encode(), body)

    def test_tampered_database_media_path_never_leaks_local_files(self):
        import sqlite3
        job_id = self.submit()
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET video_path=? WHERE job_id=?",
                       ("../private-input.mp4", job_id))
        code, headers, body = self.get(f"/media/{job_id}")
        self.assertEqual(code, 404)
        self.assertNotIn(str(self.root).encode(), body)
        # No private video location is ever included in public job status.
        code, _, page = self.get(f"/jobs/{job_id}")
        self.assertEqual(code, 200)
        self.assertNotIn(str(self.root).encode(), page)
        self.assertIn("nosniff", headers["X-Content-Type-Options"])

    def test_unknown_media_and_outside_artifact_fail_closed(self):
        status, _, body = self.get("/media/" + "0" * 32)
        self.assertEqual(status, 404)
        self.assertNotIn(str(self.root).encode(), body)

        def escaped_analyzer(video, *, out_dir):
            report = Path(out_dir) / "report.html"
            report.write_text("fake valid report")
            outside = self.root / "unsafe.mp4"
            outside.write_bytes(b"synthetic outside output")
            return {"report": report, "video": outside}

        with JobQueue(
            registry_db=self.registry,
            job_db=self.root / "jobs_unsafe.sqlite3",
            results_root=self.root / "results_unsafe",
            analyze_fn=escaped_analyzer,
        ) as worker:
            row = worker.submit(self.clip_id)
            done = worker.wait(row["job_id"], timeout=4)
            self.assertEqual(done["status"], "failed")
            self.assertEqual(done["error_code"], "invalid_report_location")


if __name__ == "__main__":
    unittest.main()
