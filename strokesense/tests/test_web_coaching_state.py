"""Offline HTTP regression: persisted coaching withholding must be visible.

Synthetic input only; this does not test real coach review, provider, or accuracy.
"""
from __future__ import annotations

import http.client
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


class WithheldJobDisplayTests(unittest.TestCase):
    def test_saved_withholding_is_visible_in_status_and_recent_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "synthetic.mov"
            video.write_bytes(b"offline fixture, not a real video")
            registry = root / "registry.sqlite3"
            clip = register_clip(
                video, registry, permission="granted",
                provenance="synthetic test-only permission claim",
            )[0]["clip_id"]
            def analyze(_, *, out_dir):
                report = out_dir / "synthetic" / "report.html"
                report.parent.mkdir(parents=True)
                report.write_text("<p>Synthetic report</p>", encoding="utf-8")
                return {"report": report}

            job_db = root / "jobs.sqlite3"
            results = root / "results"
            with JobQueue(registry_db=registry, job_db=job_db,
                          results_root=results, analyze_fn=analyze) as queue:
                job_id = queue.submit(clip)["job_id"]
                self.assertEqual(queue.wait(job_id, timeout=5)["coaching_state"], "withheld")

            # Reopen after restart to show this is persisted and not UI-local state.
            with JobQueue(registry_db=registry, job_db=job_db,
                          results_root=results, analyze_fn=analyze) as queue:
                with create_server(queue, registry_db=registry, port=0) as server:
                    thread = threading.Thread(
                        target=server.serve_forever,
                        kwargs={"poll_interval": 0.01}, daemon=True,
                    )
                    thread.start()
                    try:
                        def get(path):
                            conn = http.client.HTTPConnection(
                                "127.0.0.1", server.server_address[1], timeout=4)
                            conn.request("GET", path)
                            resp = conn.getresponse()
                            code, body = resp.status, resp.read().decode("utf-8")
                            conn.close()
                            return code, body
                        code, status_html = get("/jobs/" + job_id)
                        self.assertEqual(code, 200)
                        self.assertRegex(status_html, re.compile(
                            r"Coaching\s*:\s*(?:<[^>]*>)*withheld",
                            re.IGNORECASE))
                        self.assertNotIn("approved AI coaching", status_html)
                        code, home = get("/")
                        self.assertEqual(code, 200)
                        self.assertRegex(home, re.compile(
                            r"Analysis [0-9a-f]{12}.*coaching: withheld",
                            re.IGNORECASE))
                        self.assertNotIn(str(video), status_html + home)
                        self.assertNotIn("synthetic test-only permission claim",
                                         status_html + home)
                        # Regression after implementation: an unsupported
                        # released flag alone must never grant advisory status.
                        with sqlite3.connect(job_db) as database:
                            database.execute(
                                "UPDATE jobs SET coaching_state='released' WHERE job_id=?",
                                (job_id,),
                            )
                        self.assertEqual(get("/api/jobs/" + job_id)[0], 409)
                        self.assertEqual(get("/jobs/" + job_id)[0], 409)
                        code, home = get("/")
                        self.assertEqual(code, 200)
                        self.assertNotIn(job_id[:12], home)
                    finally:
                        server.shutdown()
                        thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
