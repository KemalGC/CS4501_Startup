"""Native form Origin contracts: synthetic loopback requests, no inference."""
from __future__ import annotations

import http.client
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import threading
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips
from strokesense.web import create_server
from test_upload import multipart, SYNTHETIC_MP4


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf":
            self.token = attrs.get("value")


class FormOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "registry.sqlite3"
        self.jobs = JobQueue(registry_db=self.db,
                             job_db=self.root / "jobs.sqlite3",
                             results_root=self.root / "results",
                             analyze_fn=lambda *a, **k: None)
        self.addCleanup(self.jobs.close)
        self.server = create_server(self.jobs, registry_db=self.db, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def page(self, host=None):
        code, headers, raw = self.request("GET", "/", headers={"Host": host} if host else None)
        self.assertEqual(code, 200)
        parser = TokenParser()
        parser.feed(raw.decode("utf-8"))
        self.assertIsNotNone(parser.token)
        return headers, parser.token

    def post(self, token, origin, host=None):
        data, content_type = multipart(token)
        headers = {"Content-Type": content_type, "Origin": origin}
        if host:
            headers["Host"] = host
        return self.request("POST", "/upload", body=data, headers=headers)

    def test_form_page_preserves_origin_without_cross_site_referrer_disclosure(self):
        headers, _ = self.page()
        self.assertEqual(headers.get("Referrer-Policy"), "same-origin")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("form-action 'self'", headers["Content-Security-Policy"])

    def test_form_post_using_served_referrer_policy_can_import(self):
        headers, token = self.page()
        # Model ONLY Fetch's same-origin, navigate-mode POST rule, not a browser.
        # browser_form_origin.py independently exercises an actual native form.
        policy = headers["Referrer-Policy"]
        self.assertIn(policy, {"no-referrer", "same-origin"})
        origin = "null" if policy == "no-referrer" else self.origin
        code, headers, _ = self.post(token, origin)
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        rows = list_clips(self.db, show_paths=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(rows[0]["source_path"]).read_bytes(), SYNTHETIC_MP4)

    def test_matching_origin_and_page_token_work_for_both_allowed_hostnames(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            with self.subTest(host=host):
                _, token = self.page(host)
                self.assertEqual(self.post(token, "http://" + host, host)[0], 303)
        self.assertEqual(len(list_clips(self.db)), 1)

    def test_null_foreign_wrong_port_and_mismatched_host_origins_stay_forbidden(self):
        _, token = self.page()
        for origin in ("null", "https://attacker.invalid", "http://127.0.0.1:1",
                       f"http://localhost:{self.port}"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post(token, origin)[0], 403)
        self.assertEqual(list_clips(self.db), [])

    def test_matching_origin_does_not_bypass_forged_csrf(self):
        self.assertEqual(self.post("forged-token", self.origin)[0], 403)
        self.assertEqual(list_clips(self.db), [])


if __name__ == "__main__":
    unittest.main()
