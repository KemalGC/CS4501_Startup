"""Browser revocation control tests: fake local video bytes, no inference."""
from __future__ import annotations

import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip, list_clips
from strokesense.web import create_server


class BrowserRevokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clip = self.root / "secret.mov"
        self.clip.write_bytes(b"synthetic bytes: not actual rowing footage")
        self.registry_db = self.root / "private-registry.sqlite3"
        self.clip_id = register_clip(
            self.clip, self.registry_db, permission="granted",
            provenance="private-fixture-consent-claim",
        )[0]["clip_id"]

        def fake(video, *, out_dir):
            report = Path(out_dir) / "report-output" / "report.html"
            report.parent.mkdir(parents=True)
            report.write_text("<h1>SYNTHETIC ONLY</h1>", encoding="utf-8")
            return {"report": report}

        self.worker = JobQueue(
            registry_db=self.registry_db, job_db=self.root / "jobs.sqlite3",
            results_root=self.root / "results", analyze_fn=fake,
        )
        item = self.worker.submit(self.clip_id)
        self.job_id = item["job_id"]
        self.assertEqual(self.worker.wait(self.job_id, timeout=5)["status"],
                         "succeeded")
        self.server = create_server(self.worker, registry_db=self.registry_db,
                                    port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=4)
        self.server.server_close()
        self.worker.close()
        self.tmp.cleanup()

    def request(self, method, path, *, form=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = urlencode(form, doseq=True).encode() if form is not None else None
        if form is not None:
            headers = {"Content-Type": "application/x-www-form-urlencoded",
                       **(headers or {})}
        conn.request(method, path, body=body, headers=headers or {})
        res = conn.getresponse()
        result = res.status, dict(res.getheaders()), res.read()
        conn.close()
        return result

    def post_revoke(self, *, clip_id=None, csrf=None, headers=None, form=None):
        fields = {
            "csrf": self.server.csrf_token if csrf is None else csrf,
            "clip_id": self.clip_id if clip_id is None else clip_id,
        }
        return self.request(
            "POST", "/revoke", form=fields if form is None else form,
            headers=headers,
        )

    def test_home_contains_explicit_csrf_guarded_withdrawal_form(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'action="/revoke"', body)
        self.assertIn(b"Withdraw analysis permission", body)
        self.assertIn(self.clip_id.encode(), body)
        self.assertNotIn(str(self.root).encode(), body)
        self.assertNotIn(b"private-fixture-consent-claim", body)

    def test_valid_withdrawal_hides_clip_and_blocks_old_report(self):
        self.assertEqual(self.request("GET", "/reports/" + self.job_id)[0],
                         200)
        status, hdr, _ = self.post_revoke()
        self.assertEqual(status, 303)
        self.assertEqual(hdr["Location"], "/")
        self.assertEqual(list_clips(self.registry_db)[0]["permission"],
                         "denied")
        status, _, home = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(self.clip_id.encode(), home)
        self.assertNotIn(self.job_id.encode(), home)
        self.assertEqual(self.request("GET", "/reports/" + self.job_id)[0],
                         403)
        self.assertTrue(self.clip.exists())

    def test_forged_invalid_and_unknown_withdrawals_do_not_mutate(self):
        for name, kwargs, expected in (
            ("csrf", {"csrf": "invalid"}, 403),
            ("origin", {"headers": {"Origin": "https://bad.invalid"}}, 403),
            ("host", {"headers": {"Host": "bad.invalid"}}, 403),
            ("invalid", {"clip_id": "../path"}, 400),
            ("unknown", {"clip_id": "f" * 64}, 422),
            ("duplicate", {"form": [("csrf", self.server.csrf_token),
                                      ("clip_id", self.clip_id),
                                      ("clip_id", self.clip_id)]}, 400),
        ):
            with self.subTest(case=name):
                status, _, body = self.post_revoke(**kwargs)
                self.assertEqual(status, expected)
                self.assertNotIn(str(self.root).encode(), body)
                self.assertEqual(list_clips(self.registry_db)[0]["permission"],
                                 "granted")
        self.assertEqual(self.request("GET", "/reports/" + self.job_id)[0],
                         200)


if __name__ == "__main__":
    unittest.main()
