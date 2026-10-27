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


    def test_all_declared_problem_statuses_use_bounded_safe_shapes(self):
        # Direct serializer matrix complements actual HTTP-path coverage.
        handler = self.server.RequestHandlerClass.__new__(
            self.server.RequestHandlerClass
        )
        handler.path = "/api/missing"
        responses = []
        handler._send = lambda code, body, **kw: responses.append(
            (code, body, kw)
        )
        for code in (400, 403, 404, 409, 413, 415, 422, 503):
            responses.clear()
            handler._error(code)
            self.assertEqual(len(responses), 1)
            observed, body, kw = responses[0]
            self.assertEqual(observed, code)
            self.assertEqual(kw["mime"], "application/problem+json")
            payload = json.loads(body)
            self.assertEqual(payload["type"], "about:blank")
            self.assertEqual(payload["status"], code)
            self.assertIsInstance(payload["title"], str)
            self.assertNotIn(str(self.root), body.decode())

    def test_real_conflict_oversize_and_backend_error_are_problem_json(self):
        source = self.root / "synthetic.mp4"
        source.write_bytes(b"synthetic fake clip only")
        clip_id = register_clip(
            source, self.root / "registry.sqlite3",
            permission="granted", provenance="offline fixture",
        )[0]["clip_id"]
        metrics = [None]

        def fake_analyzer(video, *, out_dir):
            output = Path(out_dir) / "fake"
            output.mkdir(parents=True)
            report = output / "report.html"
            report.write_text("Synthetic fake result", encoding="utf-8")
            metrics[0] = output / "metrics.json"
            metrics[0].write_text('{"evidence":{}}', encoding="utf-8")
            return {"report": report}

        self.jobs._analyze_fn = fake_analyzer
        started = self.jobs.submit(clip_id)
        self.assertEqual(self.jobs.wait(started["job_id"], timeout=5)["status"],
                         "succeeded")
        path = "/api/jobs/" + started["job_id"] + "/evidence"
        self.assert_problem(path, 409)
        with metrics[0].open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        self.assert_problem(path, 413)
        with patch.object(self.jobs, "list_recent",
                          side_effect=RuntimeError("secret private details")):
            self.assert_problem("/api/jobs", 503)
            code, headers, page = self.get("/")
            self.assertEqual(code, 503)
            self.assertTrue(headers["Content-Type"].startswith("text/html"))
            self.assertNotIn(b"secret private details", page)



if __name__ == "__main__":
    unittest.main()
