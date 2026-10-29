"""Local UI contract tests: synthetic clips, fake worker, no pose/network provider."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip


class LocalWebTests(unittest.TestCase):
    def setUp(self):
        from strokesense.web import create_server

        self.create_server = create_server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "private-video.mov"
        self.video.write_bytes(b"synthetic, not a decodable video")
        self.registry_db = self.root / "registry.sqlite3"
        self.job_db = self.root / "jobs.sqlite3"
        self.results = self.root / "results"
        self.clip_id = register_clip(
            self.video, self.registry_db, permission="granted",
            provenance="offline fake operator assertion",
            camera="<img src=x onerror=alert(1)>",
        )[0]["clip_id"]
        self.calls = []

        def analyze(video, *, out_dir):
            self.calls.append(str(video))
            p = Path(out_dir) / "run" / "report.html"
            p.parent.mkdir(parents=True)
            p.write_text("<!doctype html><h1>synthetic report</h1>")
            return {"report": p}

        self.worker = JobQueue(
            registry_db=self.registry_db, job_db=self.job_db,
            results_root=self.results, analyze_fn=analyze,
        )
        self.addCleanup(self.worker.close)
        self.server = self.create_server(self.worker, registry_db=self.registry_db, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._stop)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method, path, *, payload=None, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        if isinstance(payload, dict):
            payload = urlencode(payload)
            headers = {"Content-Type": "application/x-www-form-urlencoded",
                       **(headers or {})}
        con.request(method, path, body=payload, headers=headers or {})
        response = con.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        con.close()
        return result

    def test_reject_public_bind(self):
        with self.assertRaises(ValueError):
            self.create_server(self.worker, registry_db=self.registry_db,
                               host="0.0.0.0", port=0)

    def test_homepage_has_escaped_public_metadata_not_private_paths(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn(self.clip_id, page)
        self.assertIn("&lt;img", page)
        self.assertNotIn("<img src=x onerror", page)
        self.assertNotIn(str(self.video), page)
        self.assertNotIn("offline fake operator assertion", page)
        self.assertIn(self.server.csrf_token, page)
        self.assertIn('<nav aria-label="Primary navigation">', page)
        self.assertIn('id="content"', page)
        self.assertIn('id="upload-clip"', page)
        self.assertIn('id="recent-analyses"', page)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn("nosniff", headers["X-Content-Type-Options"])
        self.assertIn("frame-ancestors", headers["Content-Security-Policy"])
        self.assertEqual(self.calls, [])

    def test_valid_submit_status_and_scoped_report(self):
        status, headers, _ = self.request(
            "POST", "/jobs", payload={"clip_id": self.clip_id,
                                      "csrf": self.server.csrf_token},
            headers={"Origin": self.origin},
        )
        self.assertEqual(status, 303)
        self.assertIn("/jobs/", headers["Location"])
        job_id = headers["Location"].rsplit("/", 1)[-1]
        final = self.worker.wait(job_id, timeout=3)
        self.assertEqual(final["status"], "succeeded")
        s, _, body = self.request("GET", headers["Location"])
        self.assertEqual(s, 200)
        self.assertIn(f"/reports/{job_id}", body.decode())
        s, headers, body = self.request("GET", f"/reports/{job_id}")
        self.assertEqual(s, 200)
        self.assertIn(b"synthetic report", body)
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertEqual(self.calls, [str(self.video)])

    def test_csrf_token_required_without_enqueuing(self):
        for csrf in ("", "fake"):
            with self.subTest(csrf=csrf):
                s, _, b = self.request(
                    "POST", "/jobs",
                    payload={"clip_id": self.clip_id, "csrf": csrf})
                self.assertEqual(s, 403)
                self.assertNotIn(str(self.video).encode(), b)
        self.assertEqual(self.calls, [])

    def test_cross_origin_rejected_even_with_valid_token(self):
        s, _, _ = self.request(
            "POST", "/jobs", payload={"clip_id": self.clip_id,
                                       "csrf": self.server.csrf_token},
            headers={"Origin": "https://malicious.example"})
        self.assertEqual(s, 403)
        self.assertEqual(self.calls, [])

    def test_host_header_protection(self):
        s, _, _ = self.request("GET", "/", headers={"Host": "attacker.example"})
        self.assertEqual(s, 403)

    def test_oversized_or_invalid_form_rejected(self):
        s, _, _ = self.request(
            "POST", "/jobs", payload="x" * 5000,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(s, 413)
        s, _, _ = self.request(
            "POST", "/jobs", payload='{"clip_id":"x"}',
            headers={"Content-Type": "application/json"})
        self.assertEqual(s, 415)
        self.assertEqual(self.calls, [])

    def test_missing_job_and_unsafe_report_routes_do_not_serve_files(self):
        s, _, _ = self.request("GET", "/jobs/" + "0" * 32)
        self.assertEqual(s, 404)
        for path in ("/reports/../private", "/reports/" + "0" * 32,
                     "/../../private-video.mov"):
            s, _, _ = self.request("GET", path)
            self.assertEqual(s, 404)

    def test_status_json_is_privacy_safe(self):
        s, headers, _ = self.request(
            "POST", "/jobs", payload={"clip_id": self.clip_id,
                                      "csrf": self.server.csrf_token})
        self.assertEqual(s, 303)
        job_id = headers["Location"].split("/")[-1]
        self.worker.wait(job_id, timeout=3)
        s, headers, body = self.request("GET", f"/api/jobs/{job_id}")
        self.assertEqual(s, 200)
        data = json.loads(body)
        self.assertEqual(data["job_id"], job_id)
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertNotIn("offline fake operator assertion", json.dumps(data))
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_tampered_report_path_is_never_served(self):
        s, headers, _ = self.request(
            "POST", "/jobs", payload={"clip_id": self.clip_id,
                                      "csrf": self.server.csrf_token})
        self.assertEqual(s, 303)
        job_id = headers["Location"].split("/")[-1]
        self.worker.wait(job_id, timeout=3)
        outside = self.root / "private.html"
        outside.write_text("SECRET RESULT")
        with sqlite3.connect(self.job_db) as conn:
            conn.execute("UPDATE jobs SET report_path=? WHERE job_id=?",
                         ("../private.html", job_id))
        s, _, body = self.request("GET", f"/reports/{job_id}")
        self.assertEqual(s, 404)
        self.assertNotIn(b"SECRET RESULT", body)


    def test_transient_failed_job_offers_retry_without_losing_history(self):
        """The status page can resubmit the same permitted clip through POST."""
        original = self.worker._analyze_fn

        def transient(*_args, **_kwargs):
            raise RuntimeError("synthetic temporary analysis interruption")

        self.worker._analyze_fn = transient
        first = self.worker.submit(self.clip_id)["job_id"]
        self.assertEqual(self.worker.wait(first, timeout=4)["status"], "failed")
        self.assertEqual(self.worker.get(first)["error_code"], "analysis_failed")
        self.worker._analyze_fn = original

        code, _, page = self.request("GET", "/jobs/" + first)
        self.assertEqual(code, 200)
        html_page = page.decode()
        self.assertIn("Retry analysis", html_page)
        self.assertIn('action="/jobs"', html_page)
        self.assertIn('name="clip_id" value="' + self.clip_id + '"', html_page)
        self.assertIn('name="csrf" value="' + self.server.csrf_token + '"', html_page)
        self.assertNotIn(str(self.video), html_page)
        self.assertNotIn("offline fake operator assertion", html_page)

        # Retry is a regular protected /jobs submission, not a bypass.
        code, _, _ = self.request(
            "POST", "/jobs", payload={"clip_id": self.clip_id, "csrf": "wrong"},
            headers={"Origin": self.origin})
        self.assertEqual(code, 403)
        code, headers, _ = self.request(
            "POST", "/jobs",
            payload={"clip_id": self.clip_id, "csrf": self.server.csrf_token},
            headers={"Origin": self.origin})
        self.assertEqual(code, 303)
        second = headers["Location"].split("/")[-1]
        self.assertNotEqual(first, second)
        self.assertEqual(self.worker.wait(second, timeout=4)["status"], "succeeded")
        self.assertEqual(self.worker.get(first)["status"], "failed")
        self.assertEqual(self.worker.get(second)["status"], "succeeded")

    def test_permanent_media_failure_and_success_do_not_offer_retry(self):
        from strokesense.media import UndecodableMediaError

        def bad_media(*_args, **_kwargs):
            raise UndecodableMediaError("invalid_media")

        original = self.worker._analyze_fn
        self.worker._analyze_fn = bad_media
        bad = self.worker.submit(self.clip_id)["job_id"]
        self.assertEqual(self.worker.wait(bad, timeout=4)["error_code"],
                         "invalid_media")
        code, _, page = self.request("GET", "/jobs/" + bad)
        self.assertEqual(code, 200)
        self.assertNotIn(b"Retry analysis", page)
        self.worker._analyze_fn = original
        good = self.worker.submit(self.clip_id)["job_id"]
        self.assertEqual(self.worker.wait(good, timeout=4)["status"], "succeeded")
        code, _, page = self.request("GET", "/jobs/" + good)
        self.assertEqual(code, 200)
        self.assertNotIn(b"Retry analysis", page)


    def test_recent_analysis_history_shows_escaped_camera_label(self):
        job_id = self.worker.submit(self.clip_id)["job_id"]
        self.assertEqual(self.worker.wait(job_id, timeout=4)["status"], "succeeded")
        code, _, body = self.request("GET", "/")
        self.assertEqual(code, 200)
        page = body.decode()
        self.assertIn("camera: &lt;img src=x onerror=alert(1)&gt;", page)
        self.assertNotIn("<img src=x onerror", page)
        self.assertNotIn(str(self.video), page)
        self.assertNotIn("offline fake operator assertion", page)
        self.assertIn("/jobs/" + job_id, page)

    def test_recent_analysis_history_marks_unlabeled_camera_without_paths(self):
        job_id = self.worker.submit(self.clip_id)["job_id"]
        self.assertEqual(self.worker.wait(job_id, timeout=4)["status"], "succeeded")
        with sqlite3.connect(self.registry_db) as database:
            database.execute("UPDATE clips SET camera=NULL WHERE clip_id=?",
                             (self.clip_id,))
        code, _, body = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"camera: unspecified", body)
        self.assertIn(("/jobs/" + job_id).encode(), body)
        self.assertNotIn(str(self.video).encode(), body)


if __name__ == "__main__":
    unittest.main()
