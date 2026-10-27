"""Revoked-clip HTTP access tests using synthetic media and an offline fake worker."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.evidence import build_evidence_snapshot
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip, revoke_clip
from strokesense.web import create_server


class RevokedWebAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry_db = self.root / "private.sqlite3"
        self.job_db = self.root / "jobs.sqlite3"
        self.results = self.root / "results"

        def register(name, data):
            video = self.root / name
            video.write_bytes(data)
            return register_clip(video, self.registry_db, permission="granted",
                                 provenance="synthetic fixture operator claim")[0]["clip_id"]

        self.revoked_clip = register("revoked.mov", b"synthetic revoked clip bytes")
        self.allowed_clip = register("allowed.mov", b"synthetic allowed clip bytes")

        def analyze(video, *, out_dir):
            out = Path(out_dir) / "rendered"
            out.mkdir(parents=True, exist_ok=True)
            report = out / "report.html"
            report.write_text("<h1>SYNTHETIC secret report</h1>", encoding="utf-8")
            snapshot = build_evidence_snapshot(
                {"rowers": [{"seat": "synthetic-seat", "track": 1,
                             "strokes": [
                                 {"idx": 0, "catch": 1, "finish": 5,
                                  "next_catch": 10, "faults": []},
                                 {"idx": 1, "catch": 11, "finish": 16,
                                  "next_catch": 21, "faults": []},
                                 {"idx": 2, "catch": 22, "finish": 27,
                                  "next_catch": 32, "faults": []},
                             ]}]},
                analysis_key="synthetic-only-web-access", fps=15.0,
            )
            (out / "metrics.json").write_text(
                json.dumps({"evidence": snapshot}), encoding="utf-8"
            )
            return {"report": report}

        self.worker = JobQueue(
            registry_db=self.registry_db, job_db=self.job_db,
            results_root=self.results, analyze_fn=analyze,
        )
        self.server = create_server(self.worker, registry_db=self.registry_db,
                                    port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        self.thread.start()
        self.port = self.server.server_address[1]

        self.revoked_job = self._completed(self.revoked_clip)
        self.allowed_job = self._completed(self.allowed_clip)

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=4)
        self.server.server_close()
        self.worker.close()
        self.tmp.cleanup()

    def _completed(self, clip_id):
        job = self.worker.submit(clip_id)
        final = self.worker.wait(job["job_id"], timeout=5)
        self.assertEqual(final["status"], "succeeded")
        return job["job_id"]

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        result = resp.status, dict(resp.getheaders()), resp.read()
        conn.close()
        return result

    def test_withdrawn_clip_saved_endpoints_reject_without_disclosing_data(self):
        self.assertEqual(self.get("/reports/" + self.revoked_job)[0], 200)
        self.assertEqual(self.get("/api/jobs/" + self.revoked_job + "/evidence")[0], 200)
        revoke_clip(self.revoked_clip, self.registry_db)
        routes = (
            "/jobs/" + self.revoked_job,
            "/api/jobs/" + self.revoked_job,
            "/reports/" + self.revoked_job,
            "/jobs/" + self.revoked_job + "/evidence",
            "/api/jobs/" + self.revoked_job + "/evidence",
        )
        for path in routes:
            with self.subTest(route=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 403)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertNotIn(b"SYNTHETIC secret", body)
                self.assertNotIn(b"synthetic-seat", body)
                self.assertNotIn(str(self.root).encode(), body)
                if path.startswith("/api/"):
                    self.assertEqual(headers["Content-Type"],
                                     "application/problem+json")
                    self.assertEqual(json.loads(body)["status"], 403)
        # Access is withheld, not physical deletion of previously saved data.
        previous = self.worker.get(self.revoked_job)
        self.assertTrue((self.results / previous["report_path"]).is_file())

    def test_revoked_jobs_are_hidden_from_home_and_recent_api(self):
        self.assertIn(self.revoked_job.encode(), self.get("/")[2])
        revoke_clip(self.revoked_clip, self.registry_db)
        code, _, page = self.get("/")
        self.assertEqual(code, 200)
        self.assertNotIn(self.revoked_job.encode(), page)
        self.assertIn(self.allowed_job.encode(), page)
        code, hdr, body = self.get("/api/jobs")
        self.assertEqual(code, 200)
        jobs = json.loads(body)
        ids = {row["job_id"] for row in jobs}
        self.assertNotIn(self.revoked_job, ids)
        self.assertIn(self.allowed_job, ids)
        self.assertEqual(hdr["Cache-Control"], "no-store")

    def test_unrelated_granted_reports_remain_readable(self):
        revoke_clip(self.revoked_clip, self.registry_db)
        for path in (
            "/jobs/" + self.allowed_job,
            "/api/jobs/" + self.allowed_job,
            "/reports/" + self.allowed_job,
            "/jobs/" + self.allowed_job + "/evidence",
            "/api/jobs/" + self.allowed_job + "/evidence",
        ):
            with self.subTest(route=path):
                code, _, _ = self.get(path)
                self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
