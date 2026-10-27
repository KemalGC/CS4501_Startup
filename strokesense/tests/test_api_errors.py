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

    def get(self, path, *, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

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


if __name__ == "__main__":
    unittest.main()
