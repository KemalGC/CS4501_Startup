"""Local API error contracts, tested over loopback without user media/model."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


class ApiErrorContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.root = root
        self.registry_db = root / "registry.sqlite3"
        self.jobs = JobQueue(
            registry_db=self.registry_db,
            job_db=root / "jobs.sqlite3",
            results_root=root / "results",
            analyze_fn=lambda *a, **k: None,
        )
        self.addCleanup(self.jobs.close)
        self.server = create_server(
            self.jobs, registry_db=self.registry_db, port=0,
        )
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), thread.join(timeout=3)))
        self.port = self.server.server_address[1]

    def request(self, method, path, *, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def get(self, path, *, headers=None):
        return self.request("GET", path, headers=headers)

    def assert_problem(self, path, expected, *, headers=None):
        code, response_headers, body = self.get(path, headers=headers)
        self.assertEqual(code, expected)
        self.assertEqual(
            response_headers["Content-Type"], "application/problem+json"
        )
        self.assertEqual(response_headers["Cache-Control"], "no-store")
        self.assertEqual(response_headers["X-Content-Type-Options"], "nosniff")
        obj = json.loads(body)
        self.assertEqual(obj["type"], "about:blank")
        self.assertEqual(obj["status"], expected)
        self.assertIsInstance(obj["title"], str)
        self.assertNotIn("traceback", body.decode().lower())
        self.assertNotIn("sqlite", body.decode().lower())
        self.assertNotIn("/tmp/", body.decode())

    def test_missing_and_bad_job_ids_use_problem_json(self):
        for path in (
            "/api/jobs/not-a-job-id",
            "/api/jobs/" + "0" * 32,
            "/api/jobs/" + "0" * 32 + "/evidence",
        ):
            with self.subTest(path=path):
                self.assert_problem(path, 404)

    def test_host_and_origin_rejections_are_machine_readable(self):
        self.assert_problem(
            "/api/jobs", 403, headers={"Host": "attacker.invalid"}
        )
        self.assert_problem(
            "/api/jobs", 403, headers={"Origin": "https://attacker.invalid"}
        )

    def test_browser_routes_keep_escaped_html_errors(self):
        code, headers, body = self.get("/jobs/" + "0" * 32)
        self.assertEqual(code, 404)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"Request unavailable", body)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_unsupported_api_methods_are_405_problems_not_framework_html(self):
        # Unsupported verbs currently escape through BaseHTTPRequestHandler's
        # unprotected default 501 HTML. They must be safe local API responses.
        routes = ("/api/jobs", "/api/jobs/" + "0" * 32,
                  "/api/jobs/" + "0" * 32 + "/evidence")
        for route in routes:
            for method in ("HEAD", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
                with self.subTest(route=route, method=method):
                    status, headers, raw = self.request(method, route)
                    self.assertEqual(status, 405)
                    self.assertEqual(headers.get("Allow"), "GET")
                    self.assertEqual(headers["Content-Type"],
                                     "application/problem+json")
                    self.assertEqual(headers["Cache-Control"], "no-store")
                    self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn("frame-ancestors", headers["Content-Security-Policy"])
                    if method == "HEAD":
                        # HEAD must never send a body.
                        self.assertEqual(raw, b"")
                    else:
                        self.assertEqual(
                            json.loads(raw),
                            {"type": "about:blank", "title": "Method Not Allowed",
                             "status": 405},
                        )

    def test_unsupported_api_verbs_enforce_host_and_origin(self):
        for method, headers in (
            ("PUT", {"Host": "external.invalid"}),
            ("DELETE", {"Origin": "https://external.invalid"}),
            ("OPTIONS", {"Host": "wrong-host.invalid"}),
        ):
            with self.subTest(method=method, headers=headers):
                status, reply_headers, body = self.request(
                    method, "/api/jobs", headers=headers,
                )
                self.assertEqual(status, 403)
                self.assertEqual(reply_headers["Content-Type"],
                                 "application/problem+json")
                self.assertEqual(reply_headers["Cache-Control"], "no-store")
                self.assertEqual(json.loads(body)["status"], 403)

    def test_browser_method_errors_remain_html_and_route_specific(self):
        for route in ("/revoke", "/upload", "/jobs"):
            with self.subTest(route=route):
                status, headers, body = self.get(route)
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("Allow"), "POST")
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn(b"Request unavailable", body)
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_extension_http_verbs_do_not_escape_to_framework_501(self):
        # Python's HTTP handler falls back to unsanitized 501 HTML for an
        # arbitrary unrecognized method unless we provide a safe fallback.
        for method in ("BREW", "PROPFIND"):
            with self.subTest(method=method):
                code, headers, body = self.request(method, "/api/jobs")
                self.assertEqual(code, 405)
                self.assertEqual(headers["Content-Type"],
                                 "application/problem+json")
                self.assertEqual(headers["Allow"], "GET")
                self.assertEqual(json.loads(body)["status"], 405)
                self.assertEqual(headers["Cache-Control"], "no-store")
        code, headers, body = self.request(
            "BREW", "/api/jobs", headers={"Origin": "https://evil.invalid"})
        self.assertEqual(code, 403)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertEqual(json.loads(body)["status"], 403)

    def make_synthetic_completed_job(self):
        """Generate fake report paths locally; never decode/analyze footage."""
        source = self.root / "synthetic.mov"
        source.write_bytes(b"synthetic bytes, not rowing footage")
        clip_id = register_clip(
            source, self.registry_db, permission="granted",
            provenance="test-only operator assertion",
        )[0]["clip_id"]

        def fake_analyze(video, *, out_dir):
            report = Path(out_dir) / "fixture" / "report.html"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("<h1>synthetic fixture</h1>", encoding="utf-8")
            (report.parent / "metrics.json").write_text("{}", encoding="utf-8")
            return {"report": report}

        self.jobs._analyze_fn = fake_analyze
        item = self.jobs.submit(clip_id)
        record = self.jobs.wait(item["job_id"], timeout=5)
        self.assertEqual(record["status"], "succeeded")
        return item["job_id"], self.jobs._results_root / record["report_path"]

    def test_invalid_saved_evidence_is_409_problem_not_untrusted_body(self):
        job_id, report = self.make_synthetic_completed_job()
        metrics = report.parent / "metrics.json"
        metrics.write_text('{"untrusted": "/tmp/private_video.mov"}', encoding="utf-8")
        self.assert_problem(f"/api/jobs/{job_id}/evidence", 409)
        code, headers, body = self.get(f"/jobs/{job_id}/evidence")
        self.assertEqual(code, 409)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"Request unavailable", body)
        self.assertNotIn(b"private_video", body)

    def test_oversized_saved_evidence_is_413_problem_without_reading_content(self):
        job_id, report = self.make_synthetic_completed_job()
        metrics = report.parent / "metrics.json"
        with metrics.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        self.assert_problem(f"/api/jobs/{job_id}/evidence", 413)

    def test_status_storage_fault_is_503_without_private_error_details(self):
        with patch.object(self.jobs, "get",
                          side_effect=RuntimeError("secret /tmp/private-clips.db")):
            self.assert_problem("/api/jobs/" + "0" * 32, 503)
        with patch.object(self.jobs, "list_recent",
                          side_effect=RuntimeError("secret connection details")):
            self.assert_problem("/api/jobs", 503)

    def test_problem_serializer_maps_all_documented_error_codes(self):
        # Test only the shared responder with an injected test-only route.
        # This is NOT a claim every status has an existing production endpoint.
        handler = self.server.RequestHandlerClass
        original = handler.do_GET

        def synthetic_error_route(instance):
            if instance.path.startswith("/api/_contract_test/"):
                if not instance._trusted_request():
                    instance._error(403)
                    return
                instance._error(int(instance.path.rsplit("/", 1)[-1]))
                return
            return original(instance)

        handler.do_GET = synthetic_error_route
        self.addCleanup(setattr, handler, "do_GET", original)
        for code in (400, 403, 404, 405, 409, 413, 415, 422, 503):
            with self.subTest(status=code):
                self.assert_problem(f"/api/_contract_test/{code}", code)


if __name__ == "__main__":
    unittest.main()
