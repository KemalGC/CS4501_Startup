"""Local API error contracts, tested over loopback without user media/model."""
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
from strokesense.web import create_server


class ApiErrorContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.jobs = JobQueue(
            registry_db=root / "registry.sqlite3",
            job_db=root / "jobs.sqlite3",
            results_root=root / "results",
            analyze_fn=lambda *a, **k: None,
        )
        self.addCleanup(self.jobs.close)
        self.server = create_server(
            self.jobs, registry_db=root / "registry.sqlite3", port=0,
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


if __name__ == "__main__":
    unittest.main()
