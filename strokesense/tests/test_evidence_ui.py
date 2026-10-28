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
        self.with_video = False

        def fake(video, *, out_dir):
            dest = Path(out_dir) / "demo"
            dest.mkdir(parents=True)
            (dest / "report.html").write_text("<h1>offline fixture</h1>")
            self.metrics_path = dest / "metrics.json"
            self.metrics_path.write_text(json.dumps({
                "rowers": [{"private_bad_key": str(self.root)}],
                "evidence": self.snapshot,
            }))
            if self.with_video:
                # Invented bytes only: tests exercise private HTTP wiring,
                # not browser decoding of an actual playable recording.
                media = dest / "annotated.mp4"
                media.write_bytes(b"synthetic annotated media fixture")
                return {"report": dest / "report.html", "video": media}
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

    def test_saved_strokes_offer_timecoded_video_navigation_when_media_exists(self):
        """Validated evidence should link the exact saved catch to local video."""
        self.with_video = True
        job_id = self.succeed()
        status, headers, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(page.count(b"Watch catch"), 3)
        self.assertIn(f'href="/jobs/{job_id}?at=1.2"'.encode(), page)
        self.assertIn(f'href="/jobs/{job_id}?at=3"'.encode(), page)
        self.assertNotIn(str(self.root).encode(), page)

        status, headers, player = self.request(f"/jobs/{job_id}?at=1.2")
        self.assertEqual(status, 200)
        self.assertIn(f'src="/media/{job_id}#t=1.2"'.encode(), player)
        self.assertIn(b"Generated coaching", page)
        self.assertIn(b"withheld", player.lower())
        self.assertIn("media-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn(str(self.root).encode(), player)

    def test_trimmed_recording_uses_relative_video_position(self):
        """Rendered clips start at zero even when evidence is source-relative."""
        import copy
        self.snapshot = copy.deepcopy(self.snapshot)
        self.snapshot["start_seconds"] = 10.0
        for stroke in self.snapshot["strokes"]:
            for key in ("catch_seconds", "finish_seconds",
                        "next_catch_seconds"):
                stroke[key] += 10.0
        self.snapshot["snapshot_sha256"] = evidence._digest({
            key: val for key, val in self.snapshot.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(
            evidence.validate_public_evidence_snapshot(self.snapshot)
        )
        self.with_video = True
        job_id = self.succeed()
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(f'href="/jobs/{job_id}?at=1.2"'.encode(), page)
        self.assertNotIn(f'href="/jobs/{job_id}?at=11.2"'.encode(), page)

    def test_finding_offers_direct_link_to_first_saved_supporting_catch(self):
        """From a fault summary, inspect a verified supporting stroke in video."""
        self.with_video = True
        job_id = self.succeed()
        status, headers, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        findings = page.decode().split("<h2>Candidate findings</h2>", 1)[1]
        findings = findings.split("</ul>", 1)[0]
        self.assertIn("Watch first example", findings)
        self.assertIn(f'href="/jobs/{job_id}?at=1.2"', findings)
        self.assertIn("candidate_unreviewed", findings)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(str(self.root), findings)

    def test_legacy_finding_with_no_annotated_video_has_no_watch_link(self):
        job_id = self.succeed()
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Watch first example", page)
        self.assertIn(b"supporting strokes", page)

    def test_finding_example_link_uses_relative_trimmed_clip_time(self):
        import copy
        self.snapshot = copy.deepcopy(self.snapshot)
        self.snapshot["start_seconds"] = 10.0
        for stroke in self.snapshot["strokes"]:
            for key in ("catch_seconds", "finish_seconds", "next_catch_seconds"):
                stroke[key] += 10.0
        self.snapshot["snapshot_sha256"] = evidence._digest({
            key: val for key, val in self.snapshot.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(self.snapshot))
        self.with_video = True
        job_id = self.succeed()
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        findings = page.decode().split("<h2>Candidate findings</h2>", 1)[1]
        findings = findings.split("</ul>", 1)[0]
        self.assertIn(f'href="/jobs/{job_id}?at=1.2"', findings)
        self.assertNotIn(f'href="/jobs/{job_id}?at=11.2"', findings)

    def test_no_saved_video_does_not_offer_dead_seek_links(self):
        job_id = self.succeed()
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Watch catch", page)
        self.assertIn(b"Catch 1.2 s", page)

    def test_timeline_seek_rejects_ambiguous_or_unbounded_query(self):
        self.with_video = True
        job_id = self.succeed()
        for query in ("at=NaN", "at=Infinity", "at=-1", "at=121",
                      "at=1e3", "at=1.1234", "at=", "at=1.2&at=3",
                      "at=1.2&other=abc", "other=abc", "at=%3Cscript%3E"):
            with self.subTest(query=query):
                status, headers, response = self.request(
                    f"/jobs/{job_id}?{query}"
                )
                self.assertEqual(status, 400)
                self.assertIn("no-store", headers["Cache-Control"])
                self.assertNotIn(str(self.root).encode(), response)
                self.assertNotIn(b"<video", response)

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
        snap = copy.deepcopy(self.snapshot)
        snap["seats"][0]["seat"] = '<script>alert("unsafe")</script>'
        snap["snapshot_sha256"] = evidence._digest({
            key: val for key, val in snap.items() if key != "snapshot_sha256"
        })
        # Put the untrusted seat label into the original report, BEFORE job
        # success records its digest; editing afterward must now be rejected.
        self.snapshot = snap
        job_id = self.succeed()
        status, _, body = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertNotIn(b"<script>", body)
        self.assertIn(b"&lt;script&gt;", body)


    def test_findings_link_to_exact_saved_stroke_times(self):
        """Coach can jump from a finding to its real stored stroke reference."""
        job_id = self.succeed()
        status, headers, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        html_page = page.decode("utf-8")
        self.assertIn('id="stroke-0"', html_page)
        self.assertIn('href="#stroke-0"', html_page)
        self.assertIn("1 of 3 analyzed strokes", html_page)
        self.assertIn("Catch 1.2 s", html_page)
        self.assertIn("finish 1.8 s", html_page)
        self.assertIn("Generated coaching withheld", html_page)
        self.assertNotIn(str(self.root), html_page)
        self.assertNotIn("test-only operator claim", html_page)

    def test_findings_link_multiple_strokes_with_bounded_html(self):
        """The HTML link list is bounded; JSON retains all saved references."""
        import copy
        snap = copy.deepcopy(self.snapshot)
        snap["strokes"][1]["fault_codes"] = ["early_arms"]
        snap["findings"][0]["stroke_ids"] = ["stroke_fixture", "stroke_fixture_2"]
        snap["findings"][0]["observed_count"] = 2
        snap["findings"][0]["observed_fraction"] = 2 / 3
        snap["snapshot_sha256"] = evidence._digest({
            key: value for key, value in snap.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(snap))
        self.snapshot = snap
        job_id = self.succeed()
        # Use a smaller limit in this offline test without manufacturing
        # thousands of synthetic observations.
        with patch.object(web, "_MAX_LINKED_STROKES_PER_FINDING", 1, create=True):
            status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(b'id="stroke-0"', page)
        self.assertIn(b'id="stroke-1"', page)
        self.assertIn(b'href="#stroke-0"', page)
        self.assertNotIn(b'href="#stroke-1"', page)
        self.assertIn(b"1 more supporting stroke", page)
        status, _, raw = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(raw)["evidence"]["findings"][0]["stroke_ids"],
            ["stroke_fixture", "stroke_fixture_2"],
        )


    def test_csv_export_of_saved_strokes_uses_verified_allowlist(self):
        """Allow a coach to download the integrity-checked saved measurements."""
        import csv
        import io
        job_id = self.succeed()
        path = f"/api/jobs/{job_id}/strokes.csv"
        status, headers, body = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["seat"], "Stroke")
        self.assertEqual(rows[0]["stroke_index"], "0")
        self.assertEqual(rows[0]["catch_seconds"], "1.2")
        self.assertEqual(rows[0]["finish_seconds"], "1.8")
        self.assertEqual(rows[0]["fault_codes"], "early_arms")
        self.assertEqual(rows[1]["fault_codes"], "")
        self.assertNotIn(str(self.root).encode(), body)
        self.assertNotIn(b"test-only operator claim", body)
        code, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(code, 200)
        self.assertIn(path.encode("ascii"), page)
        self.assertIn(b"Export stroke evidence (CSV)", page)

    def test_csv_protects_formula_seat_and_fails_closed_on_changed_metrics(self):
        """Untrusted display labels cannot execute as spreadsheet formulas."""
        import copy
        import csv
        import io
        snap = copy.deepcopy(self.snapshot)
        snap["seats"][0]["seat"] = '=HYPERLINK("https://untrusted.invalid", "click")'
        snap["snapshot_sha256"] = evidence._digest({
            key: value for key, value in snap.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(snap))
        self.snapshot = snap
        job_id = self.succeed()
        path = f"/api/jobs/{job_id}/strokes.csv"
        status, _, content = self.request(path)
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["seat"].startswith("'=") for row in rows))
        self.metrics_path.write_text("tampered after job completion")
        status, headers, body = self.request(path)
        self.assertEqual(status, 409)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertNotIn(b"HYPERLINK", body)

    def test_blank_coach_review_csv_is_linked_and_never_claims_approval(self):
        import csv
        import io
        job_id = self.succeed()
        path = f"/api/jobs/{job_id}/review.csv"
        code, headers, body = self.request(path)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("no-store", headers["Cache-Control"])
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["stroke_id"], "stroke_fixture")
        self.assertEqual(rows[0]["seat"], "Stroke")
        self.assertEqual(rows[0]["stroke_index"], "0")
        self.assertEqual(rows[0]["catch_seconds"], "1.2")
        self.assertEqual(rows[0]["fault_codes"], "early_arms")
        self.assertTrue(all(row["coach_fault_present"] == "" for row in rows))
        self.assertTrue(all(row["coach_comments"] == "" for row in rows))
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in rows))
        self.assertNotIn(str(self.root).encode(), body)
        self.assertNotIn(b"test-only operator claim", body)
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(path.encode("ascii"), page)
        self.assertIn(b"Blank coach-review worksheet", page)

    def test_review_template_escapes_spreadsheet_formulas_in_seat_names(self):
        import copy
        import csv
        import io
        snap = copy.deepcopy(self.snapshot)
        snap["seats"][0]["seat"] = '=HYPERLINK("https://unsafe.invalid", "x")'
        snap["snapshot_sha256"] = evidence._digest({
            k: v for k, v in snap.items() if k != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(snap))
        self.snapshot = snap
        job_id = self.succeed()
        status, _, data = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        self.assertTrue(all(row["seat"].startswith("'=") for row in rows))

    def test_review_template_has_optional_saved_video_seek_position(self):
        import csv
        import io
        self.with_video = True
        job_id = self.succeed()
        code, _, content = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(content.decode())))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["video_seek_seconds"], "1.2")
        self.assertEqual(rows[1]["video_seek_seconds"], "3")
        self.assertEqual(rows[2]["video_seek_seconds"], "5")
        self.assertEqual(rows[0]["coach_fault_present"], "")
        self.assertEqual(rows[0]["review_status"], "unreviewed")
        self.assertNotIn(str(self.root).encode(), content)

    def test_review_template_without_media_keeps_seek_column_blank(self):
        import csv
        import io
        job_id = self.succeed()
        code, _, content = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(content.decode())))
        self.assertTrue(rows)
        self.assertTrue(all(row["video_seek_seconds"] == "" for row in rows))

    def test_review_template_video_time_adjusts_trimmed_source_start(self):
        import copy
        import csv
        import io
        self.snapshot = copy.deepcopy(self.snapshot)
        self.snapshot["start_seconds"] = 10.0
        for stroke in self.snapshot["strokes"]:
            for key in ("catch_seconds", "finish_seconds", "next_catch_seconds"):
                stroke[key] += 10.0
        self.snapshot["snapshot_sha256"] = evidence._digest({
            k: v for k, v in self.snapshot.items()
            if k != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(self.snapshot))
        self.with_video = True
        job_id = self.succeed()
        code, _, content = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(content.decode())))
        self.assertEqual(rows[0]["catch_seconds"], "11.2")
        self.assertEqual(rows[0]["video_seek_seconds"], "1.2")
        self.assertNotIn(b"private_bad_key", content)

    def test_review_template_video_seek_outside_supported_range_is_blank(self):
        import csv
        import io
        self.with_video = True
        job_id = self.succeed()
        # Use a low bound to exercise the same production rejection policy
        # without generating a real or hours-long video fixture.
        with patch.object(web, "_MAX_SEEK_SECONDS", 2.0):
            status, _, content = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(content.decode())))
        self.assertEqual(rows[0]["video_seek_seconds"], "1.2")
        self.assertEqual(rows[1]["video_seek_seconds"], "")
        self.assertEqual(rows[2]["video_seek_seconds"], "")
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in rows))

    def test_review_template_does_not_offer_seek_when_media_was_deleted(self):
        import csv
        import io
        self.with_video = True
        job_id = self.succeed()
        (self.metrics_path.parent / "annotated.mp4").unlink()
        code, _, body = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode())))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["video_seek_seconds"] == "" for row in rows))
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in rows))

    def test_review_template_does_not_offer_seek_for_tampered_media(self):
        import csv
        import io
        self.with_video = True
        job_id = self.succeed()
        media = self.metrics_path.parent / "annotated.mp4"
        media.write_bytes(b"changed but still a file")
        code, _, body = self.request(f"/api/jobs/{job_id}/review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode())))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["video_seek_seconds"] == "" for row in rows))

    def test_review_template_rejects_changed_evidence_and_untrusted_release(self):
        job_id = self.succeed()
        path = f"/api/jobs/{job_id}/review.csv"
        self.metrics_path.write_text("injected after completed job")
        status, headers, content = self.request(path)
        self.assertEqual(status, 409)
        self.assertNotIn(b"injected after", content)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        # Re-run with intact data before checking the forged release flag.
        self.metrics_path.write_text(json.dumps({
            "rowers": [{"private_bad_key": str(self.root)}],
            "evidence": self.snapshot,
        }))
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET coaching_state='released' WHERE job_id=?",
                       (job_id,))
        status, _, content = self.request(path)
        self.assertEqual(status, 409)
        self.assertNotIn(b"stroke_fixture", content)
        code, _, content = self.request(
            "/api/jobs/" + "0" * 32 + "/review.csv"
        )
        self.assertEqual(code, 404)
        self.assertNotIn(str(self.root).encode(), content)

    def test_fault_review_grid_exports_all_candidate_positive_and_negative_opportunities(self):
        import csv
        import io
        from strokesense.strokes import FAULTS
        job_id = self.succeed()
        url = f"/api/jobs/{job_id}/fault-review.csv"
        code, headers, body = self.request(url)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("no-store", headers["Cache-Control"])
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        self.assertEqual(len(rows), len(FAULTS) * 3)
        self.assertEqual(
            [(row["stroke_id"], row["fault_code"]) for row in rows],
            [(stroke["id"], code)
             for stroke in self.snapshot["strokes"] for code in sorted(FAULTS)],
        )
        keyed = {(row["stroke_id"], row["fault_code"]): row for row in rows}
        self.assertEqual(keyed[("stroke_fixture", "early_arms")]["predicted"], "1")
        self.assertEqual(keyed[("stroke_fixture_2", "early_arms")]["predicted"], "0")
        self.assertEqual(keyed[("stroke_fixture_3", "early_arms")]["predicted"], "0")
        self.assertEqual(keyed[("stroke_fixture", "early_arms")]["seat_id"],
                         "seat_fixture")
        self.assertTrue(all(row["schema_version"] == "1" for row in rows))
        self.assertTrue(all(row["coach_fault_present"] == "" for row in rows))
        self.assertTrue(all(row["coach_comments"] == "" for row in rows))
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in rows))
        self.assertTrue(all(row["video_seek_seconds"] == "" for row in rows))
        self.assertNotIn(str(self.root).encode(), body)
        self.assertNotIn(b"test-only operator claim", body)
        code, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(code, 200)
        self.assertIn(url.encode("ascii"), page)

    def test_fault_review_grid_media_seek_is_conditional_on_saved_hash(self):
        import csv
        import io
        self.with_video = True
        job_id = self.succeed()
        url = f"/api/jobs/{job_id}/fault-review.csv"
        code, _, body = self.request(url)
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        self.assertEqual(rows[0]["video_seek_seconds"], "1.2")
        self.assertEqual(rows[-1]["video_seek_seconds"], "5")
        (self.metrics_path.parent / "annotated.mp4").write_bytes(b"changed")
        code, _, body = self.request(url)
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        self.assertTrue(all(row["video_seek_seconds"] == "" for row in rows))

    def test_fault_review_grid_fails_closed_for_changed_evidence_and_forged_release(self):
        import sqlite3
        job_id = self.succeed()
        url = f"/api/jobs/{job_id}/fault-review.csv"
        self.metrics_path.write_bytes(b"post-success unverified change")
        code, headers, body = self.request(url)
        self.assertEqual(code, 409)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertNotIn(b"post-success", body)
        self.metrics_path.write_text(json.dumps({"evidence": self.snapshot}))
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET coaching_state='released' WHERE job_id=?",
                       (job_id,))
        self.assertEqual(self.request(url)[0], 409)
        self.assertEqual(
            self.request("/api/jobs/" + "0" * 32 + "/fault-review.csv")[0],
            404,
        )

    def test_fault_review_grid_csv_formula_safe_seat_names(self):
        import copy
        import csv
        import io
        snap = copy.deepcopy(self.snapshot)
        snap["seats"][0]["seat"] = '=HYPERLINK("https://not-approved.invalid","x")'
        snap["snapshot_sha256"] = evidence._digest({
            key: val for key, val in snap.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(snap))
        self.snapshot = snap
        job_id = self.succeed()
        code, _, body = self.request(f"/api/jobs/{job_id}/fault-review.csv")
        self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode())))
        self.assertTrue(all(row["seat"].startswith("'=") for row in rows))

    def test_csv_unknown_job_and_untrusted_released_flag_do_not_export(self):
        unknown = "/api/jobs/" + "0" * 32 + "/strokes.csv"
        code, headers, _ = self.request(unknown)
        self.assertEqual(code, 404)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        job_id = self.succeed()
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET coaching_state='released' WHERE job_id=?",
                       (job_id,))
        code, headers, payload = self.request(
            f"/api/jobs/{job_id}/strokes.csv"
        )
        self.assertEqual(code, 409)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertNotIn(b"early_arms", payload)


    def test_fault_filter_scopes_strokes_and_findings_without_releasing_coaching(self):
        """Synthetic saved evidence: filter is a view, not new diagnosis."""
        self.with_video = True
        job_id = self.succeed()
        base = f"/jobs/{job_id}/evidence"
        all_status, _, all_page = self.request(base)
        self.assertEqual(all_status, 200)
        self.assertEqual(all_page.count(b'<li id="stroke-'), 3)

        status, headers, filtered = self.request(base + "?fault=early_arms")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn(b"Showing candidate fault", filtered)
        self.assertIn(b"early_arms", filtered)
        self.assertIn(f'<form method="get" action="{base}">'.encode(), filtered)
        self.assertIn(f'href="{base}"'.encode(), filtered)
        self.assertIn(b'<li id="stroke-0">', filtered)
        self.assertNotIn(b'<li id="stroke-1">', filtered)
        self.assertNotIn(b'<li id="stroke-2">', filtered)
        self.assertEqual(filtered.count(b'<li id="stroke-'), 1)
        self.assertEqual(filtered.count(b"Watch catch"), 1)
        self.assertIn(b"1 of 3 analyzed strokes", filtered)
        self.assertIn(b"Generated coaching withheld", filtered)
        self.assertIn(f"/api/jobs/{job_id}/fault-review.csv".encode(), filtered)
        self.assertNotIn(str(self.root).encode(), filtered)

        # UI filters never rewrite or narrow the independently saved JSON.
        api_status, _, raw = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(api_status, 200)
        self.assertEqual(len(json.loads(raw)["evidence"]["strokes"]), 3)

    def test_fault_filter_empty_result_is_explicit_and_reversible(self):
        job_id = self.succeed()
        base = f"/jobs/{job_id}/evidence"
        status, _, page = self.request(base + "?fault=short_catch")
        self.assertEqual(status, 200)
        self.assertIn(b"No strokes flagged for this candidate fault", page)
        self.assertNotIn(b'<li id="stroke-', page)
        self.assertIn(f'href="{base}"'.encode(), page)
        self.assertIn(b"Generated coaching withheld", page)
        self.assertNotIn(str(self.root).encode(), page)
        self.assertEqual(self.request(base)[2].count(b'<li id="stroke-'), 3)

    def test_fault_filter_rejects_unknown_ambiguous_and_oversized_queries(self):
        job_id = self.succeed()
        base = f"/jobs/{job_id}/evidence"
        queries = (
            "fault=unknown", "fault=", "fault",
            "fault=early_arms&fault=short_catch",
            "fault=early_arms&unexpected=1", "unexpected=1",
            "fault=%3Cscript%3E",
            "fault=early_arms" + ("x" * 130),
        )
        for query in queries:
            with self.subTest(query=query):
                status, headers, page = self.request(base + "?" + query)
                self.assertEqual(status, 400)
                self.assertIn("no-store", headers["Cache-Control"])
                self.assertNotIn(b"stroke_fixture", page)
                self.assertNotIn(str(self.root).encode(), page)

    def test_fault_filter_preserves_existing_integrity_and_permission_gates(self):
        from strokesense.registry import revoke_clip
        job_id = self.succeed()
        route = f"/jobs/{job_id}/evidence?fault=early_arms"
        self.metrics_path.write_text(json.dumps({
            "evidence": {**self.snapshot, "status": "untrusted_modified"}
        }))
        status, _, content = self.request(route)
        self.assertEqual(status, 409)
        self.assertNotIn(b"stroke_fixture", content)
        revoke_clip(self.clip_id, self.registry)
        status, _, content = self.request(route)
        self.assertEqual(status, 403)
        self.assertNotIn(str(self.root).encode(), content)


    def test_accessible_candidate_frequency_meter_uses_saved_denominator(self):
        """A 1-in-3 candidate fraction is not accuracy or LLM confidence."""
        job_id = self.succeed()
        status, headers, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(
            b'<meter min="0" max="3" value="1" '
            b'aria-label="Candidate frequency among analyzed strokes">',
            page,
        )
        self.assertIn(b"1 of 3 analyzed strokes", page)
        self.assertIn(b"Generated coaching withheld", page)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(str(self.root).encode(), page)
        # Visual components must not alter the immutable-style saved snapshot.
        code, _, raw = self.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(code, 200)
        self.assertEqual(
            json.loads(raw)["evidence"]["findings"][0]["observed_count"], 1
        )

    def test_fault_filter_only_shows_frequency_of_visible_finding(self):
        job_id = self.succeed()
        base = f"/jobs/{job_id}/evidence"
        code, _, matching = self.request(base + "?fault=early_arms")
        self.assertEqual(code, 200)
        self.assertEqual(matching.count(b"<meter "), 1)
        code, _, none = self.request(base + "?fault=short_catch")
        self.assertEqual(code, 200)
        self.assertNotIn(b"<meter ", none)
        self.assertIn(b"No strokes flagged for this candidate fault", none)
        self.assertNotIn(str(self.root).encode(), matching + none)

    def test_no_saved_findings_creates_no_illusory_frequency_meter(self):
        import copy
        snap = copy.deepcopy(self.snapshot)
        snap["strokes"][0]["fault_codes"] = []
        snap["findings"] = []
        snap["snapshot_sha256"] = evidence._digest({
            key: value for key, value in snap.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(snap))
        self.snapshot = snap
        job_id = self.succeed()
        status, _, page = self.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(b"Candidate findings", page)
        self.assertNotIn(b"<meter ", page)
        self.assertIn(b"Generated coaching withheld", page)


if __name__ == "__main__":
    unittest.main()
