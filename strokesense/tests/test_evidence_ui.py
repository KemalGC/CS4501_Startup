"""Fail-closed evidence navigation contract; synthetic snapshot, no real labels."""
from __future__ import annotations

import http.client
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import evidence
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server
import strokesense.web as web


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
                     "fault_codes": ["early_arms"]},
                    {"id": "stroke_fixture_2", "seat_id": "seat_fixture",
                     "index": 1, "catch_frame": 45, "finish_frame": 55,
                     "next_catch_frame": 75, "catch_seconds": 3.0,
                     "finish_seconds": 55 / 15, "next_catch_seconds": 5.0,
                     "fault_codes": []},
                    {"id": "stroke_fixture_3", "seat_id": "seat_fixture",
                     "index": 2, "catch_frame": 75, "finish_frame": 85,
                     "next_catch_frame": 105, "catch_seconds": 5.0,
                     "finish_seconds": 85 / 15, "next_catch_seconds": 7.0,
                     "fault_codes": []}],
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

    def test_unverified_release_flag_blocks_all_result_surfaces(self):
        """A stored flag is not independent evidence of verified coaching."""
        job_id = self.succeed()
        endpoints = (
            f"/reports/{job_id}",
            f"/jobs/{job_id}/evidence",
            f"/api/jobs/{job_id}/evidence",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint, state="withheld"):
                status, _, body = self.request(endpoint)
                self.assertEqual(status, 200)
                self.assertTrue(body)

        # This simulates corrupted/unauthorized persisted metadata, NOT a
        # genuine coach-approved release. The Alpha has no release pathway.
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute(
                "UPDATE jobs SET coaching_state='released' WHERE job_id=?",
                (job_id,),
            )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint, state="unverified-release"):
                status, headers, body = self.request(endpoint)
                self.assertEqual(status, 409)
                self.assertNotIn(b"offline fixture", body)
                self.assertNotIn(b"finding_fixture", body)
                self.assertNotIn(str(self.root).encode(), body)
                self.assertIn("no-store", headers["Cache-Control"])
                if endpoint.startswith("/api/"):
                    self.assertEqual(
                        headers["Content-Type"], "application/problem+json"
                    )

    def test_report_read_rejects_growth_past_response_bound(self):
        """A stale small stat size must not authorize an oversized response."""
        job_id = self.succeed()
        report_path = self.metrics_path.parent / "report.html"
        original_stat = Path.stat

        def stale_small_size(path, *args, **kwargs):
            stat = original_stat(path, *args, **kwargs)
            if path == report_path:
                values = list(stat)
                values[6] = 1  # Simulates a pre-read metadata snapshot.
                return os.stat_result(values)
            return stat

        # Lower the production limit for this synthetic regression so CI need
        # not allocate a 32 MiB video/report to exercise the race.
        with patch.object(web, "_MAX_REPORT", 16), patch.object(
            Path, "stat", stale_small_size
        ):
            status, headers, body = self.request(f"/reports/{job_id}")
        self.assertEqual(status, 413)
        self.assertNotIn(b"offline fixture", body)
        self.assertIn("no-store", headers["Cache-Control"])

    def test_evidence_read_rejects_growth_past_metrics_bound(self):
        """Unbounded metrics.read_text must not bypass an old small stat."""
        job_id = self.succeed()
        metrics_path = self.metrics_path
        original_stat = Path.stat

        def stale_small_size(path, *args, **kwargs):
            stat = original_stat(path, *args, **kwargs)
            if path == metrics_path:
                values = list(stat)
                values[6] = 1
                return os.stat_result(values)
            return stat

        # create=True permits the test to go red against the old hard-coded
        # limit, before the production limit constant is introduced.
        with patch.object(web, "_MAX_METRICS", 16, create=True), patch.object(
            Path, "stat", stale_small_size
        ):
            status, headers, body = self.request(
                f"/api/jobs/{job_id}/evidence"
            )
        self.assertEqual(status, 413)
        self.assertNotIn(b"finding_fixture", body)
        self.assertEqual(headers["Content-Type"], "application/problem+json")

    def test_changed_completed_report_fails_closed_across_result_endpoints(self):
        """Saved report content is not trusted after a successful job."""
        job_id = self.succeed()
        report_path = self.metrics_path.parent / "report.html"
        routes = (
            f"/reports/{job_id}",
            f"/jobs/{job_id}/evidence",
            f"/api/jobs/{job_id}/evidence",
        )
        for route in routes:
            with self.subTest(route=route, stage="before"):
                self.assertEqual(self.request(route)[0], 200)

        report_path.write_text(
            "<!doctype html><h1>UNVERIFIED ADVICE injected after analysis</h1>",
            encoding="utf-8",
        )
        for route in routes:
            with self.subTest(route=route, stage="after"):
                status, _, body = self.request(route)
                self.assertEqual(status, 409)
                self.assertNotIn(b"UNVERIFIED ADVICE", body)
                self.assertNotIn(str(self.root).encode(), body)

    def test_rehashed_changed_metrics_are_rejected_by_job_integrity(self):
        """A self-consistent snapshot checksum is not job provenance."""
        job_id = self.succeed()
        route = f"/api/jobs/{job_id}/evidence"
        self.assertEqual(self.request(route)[0], 200)
        saved = json.loads(self.metrics_path.read_text(encoding="utf-8"))
        saved["evidence"]["analysis_id"] = "post_success_replacement"
        payload = {k: v for k, v in saved["evidence"].items()
                   if k != "snapshot_sha256"}
        saved["evidence"]["snapshot_sha256"] = evidence._digest(payload)
        self.assertTrue(
            evidence.validate_public_evidence_snapshot(saved["evidence"])
        )
        self.metrics_path.write_text(json.dumps(saved), encoding="utf-8")
        for route in (route, f"/jobs/{job_id}/evidence"):
            with self.subTest(route=route):
                status, headers, body = self.request(route)
                self.assertEqual(status, 409)
                self.assertNotIn(b"post_success_replacement", body)
                self.assertNotIn(str(self.root).encode(), body)
                self.assertIn("no-store", headers["Cache-Control"])

    def test_metrics_digest_is_private_and_survives_job_restart(self):
        job_id = self.succeed()
        digest = hashlib.sha256(self.metrics_path.read_bytes()).hexdigest()
        self.assertEqual(self.worker.metrics_sha256(job_id), digest)
        status, _, body = self.request(f"/api/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertNotIn(digest.encode(), body)
        self.assertNotIn(b"metrics_sha256", body)

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


    def _serve_rehashed_snapshot(self, job_id, modified):
        """Keep the digest internally consistent to exercise schema checks."""
        import copy
        record = copy.deepcopy(self.snapshot)
        modified(record)
        record["snapshot_sha256"] = evidence._digest({
            key: val for key, val in record.items() if key != "snapshot_sha256"
        })
        self.metrics_path.write_text(json.dumps({"evidence": record}), encoding="utf-8")
        return self.request(f"/api/jobs/{job_id}/evidence")

    def test_rehashed_invalid_numeric_measurements_are_rejected(self):
        job_id = self.succeed()
        edits = (
            ("zero_fps", lambda s: s.__setitem__("fps", 0)),
            ("string_fps", lambda s: s.__setitem__("fps", "15")),
            ("string_timestamp", lambda s: s["strokes"][0].__setitem__("catch_seconds", "1.2")),
            ("negative_frame", lambda s: s["strokes"][0].__setitem__("catch_frame", -1)),
            ("fraction_outside_range", lambda s: s["findings"][0].__setitem__("observed_fraction", 9)),
        )
        for description, edit in edits:
            with self.subTest(description=description):
                status, _, body = self._serve_rehashed_snapshot(job_id, edit)
                self.assertEqual(status, 409)
                self.assertNotIn(b"analysis_fixture", body)

    def test_rehashed_inconsistent_references_and_counts_are_rejected(self):
        job_id = self.succeed()
        edits = (
            ("unknown_seat", lambda s: s["strokes"][0].__setitem__("seat_id", "missing_seat")),
            ("unknown_stroke", lambda s: s["findings"][0].__setitem__("stroke_ids", ["missing_stroke"])),
            ("contradictory_count", lambda s: s["findings"][0].__setitem__("observed_count", 3)),
            ("seat_count_mismatch", lambda s: s["seats"][0].__setitem__("analyzed_strokes", 100)),
            ("duplicate_seat", lambda s: s["seats"].append(dict(s["seats"][0]))),
        )
        for description, edit in edits:
            with self.subTest(description=description):
                status, _, _ = self._serve_rehashed_snapshot(job_id, edit)
                self.assertEqual(status, 409)

    def test_rehashed_unreviewed_snapshot_cannot_fake_release_eligibility(self):
        job_id = self.succeed()
        edits = (
            ("false_review", lambda s: s["findings"][0].update({
                "status": "reviewed_supported", "eligible_strokes": 3,
                "coaching_eligible": True,
            })),
            ("fake_top_level_approval", lambda s: s.__setitem__("status", "reviewed_supported")),
        )
        for description, edit in edits:
            with self.subTest(description=description):
                status, _, body = self._serve_rehashed_snapshot(job_id, edit)
                self.assertEqual(status, 409)
                self.assertNotIn(b"reviewed_supported", body)


    def test_oversized_metrics_are_refused_without_parsing(self):
        job_id = self.succeed()
        with self.metrics_path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        status, _, body = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(status, 413)
        self.assertNotIn(str(self.root).encode(), body)

    def test_unsupported_snapshot_schema_is_refused(self):
        job_id = self.succeed()
        status, _, body = self._serve_rehashed_snapshot(
            job_id, lambda s: s.__setitem__("schema_version", 2))
        self.assertEqual(status, 409)
        self.assertNotIn(b"analysis_fixture", body)

    def test_evidence_html_escapes_source_controlled_seat_names(self):
        import copy
        job_id = self.succeed()
        snap = copy.deepcopy(self.snapshot)
        snap["seats"][0]["seat"] = '<script>alert("unsafe")</script>'
        snap["snapshot_sha256"] = evidence._digest({
            key: val for key, val in snap.items() if key != "snapshot_sha256"
        })
        self.metrics_path.write_text(json.dumps({"evidence": snap}), encoding="utf-8")
        status, _, body = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertNotIn(b"<script>", body)
        self.assertIn(b"&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()
