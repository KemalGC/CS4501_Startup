"""Synthetic loopback HTTP contract for incomplete form bodies (issue #42)."""
from __future__ import annotations

import http.client
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips, register_clip
from strokesense.web import create_server


class IncompletePostBodyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        video = root / "synthetic.mov"
        video.write_bytes(b"not a real video")
        self.registry = root / "registry.sqlite3"
        self.clip_id = register_clip(
            video, self.registry, permission="granted",
            provenance="synthetic permission declaration",
        )[0]["clip_id"]
        self.jobs = JobQueue(
            registry_db=self.registry,
            job_db=root / "jobs.sqlite3",
            results_root=root / "results",
            analyze_fn=lambda video, *, out_dir: {},
        )
        self.addCleanup(self.jobs.close)
        self.server = create_server(self.jobs, registry_db=self.registry, port=0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01}, daemon=True,
        )
        thread.start()
        def stop():
            self.server.shutdown()
            thread.join(timeout=3)
        self.addCleanup(stop)
        self.port = self.server.server_address[1]

    def raw_post(self, route, *, keep_write_open=False):
        data = urlencode({
            "csrf": self.server.csrf_token, "clip_id": self.clip_id,
        }).encode("ascii")
        header = (
            f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            f"Content-Length: {len(data) + 9}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        with socket.create_connection(("127.0.0.1", self.port), timeout=8) as client:
            client.settimeout(8)
            client.sendall(header + data)
            if not keep_write_open:
                client.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        return int(response.split(b" ", 2)[1]), response

    def test_short_eof_must_not_enqueue_a_job(self):
        status, response = self.raw_post("/jobs")
        self.assertEqual(status, 400)
        self.assertEqual(self.jobs.list_recent(), [])
        self.assertNotIn(self.server.csrf_token.encode(), response)

    def test_short_eof_must_not_withdraw_permission(self):
        status, response = self.raw_post("/revoke")
        self.assertEqual(status, 400)
        self.assertEqual(list_clips(self.registry)[0]["permission"], "granted")
        self.assertNotIn(self.server.csrf_token.encode(), response)

    def test_body_read_timeout_must_not_process_partial_form(self):
        status, _ = self.raw_post("/revoke", keep_write_open=True)
        self.assertEqual(status, 400)
        self.assertEqual(list_clips(self.registry)[0]["permission"], "granted")

    def test_valid_form_still_accepted(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = urlencode({"csrf": self.server.csrf_token, "clip_id": self.clip_id})
        conn.request("POST", "/jobs", body=body, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        response = conn.getresponse()
        self.assertEqual(response.status, 303)
        response.read()
        conn.close()


if __name__ == "__main__":
    unittest.main()
