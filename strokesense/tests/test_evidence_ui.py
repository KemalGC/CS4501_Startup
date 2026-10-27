"""Fail-closed evidence navigation contract; synthetic snapshot, no real labels."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import evidence
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


def example_snapshot():
    snap = {
        "schema_version": 1, "analysis_id": "analysis_fixture",
        "fps": 15.0, "start_seconds": 0.0,
        "status": "candidate_unreviewed",
        "seats": [{"id": "seat_fixture", "seat": "Stroke",
                   "analyzed_strokes": 3, "status": "candidate_unreviewed"}],
        "strokes": [{"id": "stroke_fixture", "seat_id": "seat_fixture",
                     "index": 0, "catch_frame": 18, "finish_frame": 27,
                     "next_catch_frame": 45, "catch_seconds": 1.2,
                     "finish_seconds": 1.8, "next_catch_seconds": 3.0,
                     "fault_codes": ["early_arms"]}],
        "findings": [{"id": "finding_fixture", "seat_id": "seat_fixture",
                      "fault_code": "early_arms", "stroke_ids": ["stroke_fixture"],
                      "observed_count": 1, "analyzed_strokes": 3,
                      "observed_fraction": 1 / 3,
                      "eligible_strokes": None, "status": "candidate_unreviewed",
                      "coaching_eligible": False}],
        "quality_limitations": ["synthetic_fixture_not_real_review"],
    }
    snap["snapshot_sha256"] = evidence._digest(snap)
    return snap


class EvidenceInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        src = self.root / "private.mov"
        src.write_bytes(b"synthetic test bytes")
        self.registry = self.root / "registry.sqlite3"
        self.clip_id = register_clip(
            src, self.registry, permission="granted",
            provenance="test-only operator claim")[0]["clip_id"]
        self.metrics_path = None
        self.snapshot = example_snapshot()

        def fake(video, *, out_dir):
            dest = Path(out_dir) / "demo"
            dest.mkdir(parents=True)
            (dest / "report.html").write_text("<h1>offline fixture</h1>")
            self.metrics_path = dest / "metrics.json"
            self.metrics_path.write_text(json.dumps({
                "rowers": [{"private_bad_key": str(self.root)}],
                "evidence": self.snapshot,
            }))
            return {"report": dest / "report.html"}

        self.worker = JobQueue(
            registry_db=self.registry, job_db=self.root / "jobs.sqlite3",
            results_root=self.root / "outputs", analyze_fn=fake,
        )
        self.addCleanup(self.worker.close)
        self.server = create_server(self.worker, registry_db=self.registry, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.thread.join(timeout=3)))
        self.port = self.server.server_address[1]

    def request(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("GET", path)
        res = conn.getresponse()
        output = (res.status, dict(res.getheaders()), res.read())
        conn.close()
        return output

    def succeed(self):
        row = self.worker.submit(self.clip_id)
        done = self.worker.wait(row["job_id"], timeout=5)
        self.assertEqual(done["status"], "succeeded")
        return row["job_id"]

    def test_valid_snapshot_navigation_returns_only_verified_evidence(self):
        job_id = self.succeed()
        status, hdr, body = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["coaching_state"], "withheld")
        self.assertEqual(payload["evidence"]["analysis_id"], "analysis_fixture")
        self.assertTrue(payload["evidence"]["findings"])
        self.assertNotIn("rowers", payload)
        self.assertNotIn(str(self.root), body.decode())
        self.assertIn("no-store", hdr["Cache-Control"])

    def test_human_readable_evidence_links_to_strokes_and_times(self):
        job_id = self.succeed()
        status, _, body = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        content = body.decode()
        self.assertIn("Stroke", content)
        self.assertIn("1.2", content)
        self.assertIn("early_arms", content)
        self.assertIn("withheld", content.lower())
        self.assertNotIn(str(self.root), content)

    def test_job_status_offers_evidence_link_without_approving_coaching(self):
        job_id = self.succeed()
        status, _, body = self.request(f"/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertIn(f"/jobs/{job_id}/evidence".encode(), body)
        self.assertNotIn(b"AI coaching verified", body)

    def test_tampered_evidence_is_never_served(self):
        job_id = self.succeed()
        self.metrics_path.write_text(json.dumps({
            "evidence": {**self.snapshot, "status": "verified"}
        }))
        status, _, body = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertNotEqual(status, 200)
        self.assertNotIn(b"verified", body)

    def test_unsuccessful_or_unknown_jobs_do_not_expose_evidence(self):
        status, _, _ = self.request("/api/jobs/" + "0" * 32 + "/evidence")
        self.assertEqual(status, 404)
        self.worker._analyze_fn = lambda *a, **kw: None
        job = self.worker.submit(self.clip_id)
        self.assertEqual(self.worker.wait(job["job_id"], timeout=5)["status"], "failed")
        status, _, _ = self.request(f"/api/jobs/{job['job_id']}/evidence")
        self.assertEqual(status, 404)

    def test_untrusted_metrics_symlink_outside_job_is_rejected(self):
        job_id = self.succeed()
        outside = self.root / "private-metrics.json"
        outside.write_text(json.dumps({"evidence": self.snapshot}))
        self.metrics_path.unlink()
        try:
            self.metrics_path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        status, _, body = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertNotEqual(status, 200)
        self.assertNotIn(str(self.root).encode(), body)


if __name__ == "__main__":
    unittest.main()
