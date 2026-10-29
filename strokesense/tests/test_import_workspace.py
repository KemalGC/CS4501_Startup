"""HTML and HTTP acceptance tests for the guided local import workspace (#90).

Fixtures are synthetic container headers, not playable footage or AI inference.
"""
from __future__ import annotations

import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips
from strokesense.web import create_server


SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12


class GuidedImportWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.registry = root / "registry.sqlite3"
        self.jobs = JobQueue(
            registry_db=self.registry, job_db=root / "jobs.sqlite3",
            results_root=root / "results", analyze_fn=lambda *args: None,
        )
        self.addCleanup(self.jobs.close)
        self.server = create_server(self.jobs, registry_db=self.registry, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method="GET", path="/", body=None, *, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def upload_fragment(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers["Content-Type"])
        page = body.decode("utf-8")
        self.assertIn('action="/upload"', page)
        fragment = page.split('<form method="post" action="/upload" enctype="multipart/form-data">', 1)[1].split("</form>", 1)[0]
        return page, fragment

    def test_import_has_visually_distinct_two_step_landmarks(self):
        page, fragment = self.upload_fragment()
        self.assertIn('<section class="import-panel" aria-labelledby="upload-clip">', page)
        self.assertIn('<h2 id="upload-clip">Register a new local clip</h2>', page)
        self.assertIn('<fieldset class="import-stage import-file">', fragment)
        self.assertIn('<fieldset class="import-stage import-permission">', fragment)
        self.assertIn("Choose a recording", fragment)
        self.assertIn("Confirm permission", fragment)
        self.assertLess(fragment.index("Choose a recording"),
                        fragment.index("Confirm permission"))
        self.assertIn("Private on this device", page)
        self.assertIn("150 MiB", fragment)
        self.assertNotIn("Drop files here", page)  # No imaginary dropzone.

    def test_native_picker_and_attestations_are_explicitly_labeled(self):
        _, fragment = self.upload_fragment()
        self.assertIn('id="upload-video"', fragment)
        self.assertIn('type="file" name="video" required', fragment)
        self.assertIn('aria-describedby="upload-video-help"', fragment)
        self.assertIn('id="upload-video-help"', fragment)
        self.assertIn('accept=".mp4,.mov,.mkv,.avi,.webm"', fragment)
        self.assertIn('name="permission" value="granted" required', fragment)
        self.assertIn('name="provenance" maxlength="256" required', fragment)
        self.assertIn('name="camera"', fragment)
        self.assertIn('name="analyze" value="now" checked', fragment)
        self.assertIn('name="csrf"', fragment)
        self.assertIn('class="import-actions"', fragment)
        self.assertIn("Import locally", fragment)

    def test_layout_uses_responsive_import_cards_and_no_external_assets(self):
        page, _ = self.upload_fragment()
        self.assertIn(".import-panel", page)
        self.assertIn(".import-stage", page)
        self.assertIn(".import-actions", page)
        self.assertIn(".import-file input[type=\"file\"]", page)
        self.assertIn("@media (max-width: 720px)", page)
        self.assertIn(":focus-visible", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertNotIn("<script", page)
        self.assertNotIn('<link rel="stylesheet"', page)

    def test_same_origin_post_still_registers_synthetic_bytes(self):
        self.upload_fragment()
        token = self.server.csrf_token
        boundary = "GuidedImportTestBoundary"
        fields = (("csrf", token), ("permission", "granted"),
                  ("provenance", "synthetic consent reference"),
                  ("camera", "side-on"))
        blocks = []
        for name, value in fields:
            blocks.append(
                (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                 f'\r\n\r\n{value}\r\n').encode("utf-8")
            )
        blocks.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="video";'
             f' filename="fixture.mp4"\r\nContent-Type: video/mp4'
             f'\r\n\r\n').encode("ascii")
            + SYNTHETIC_MP4 + b"\r\n"
        )
        blocks.append(f"--{boundary}--\r\n".encode("ascii"))
        code, headers, _ = self.request(
            "POST", "/upload", body=b"".join(blocks),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": f"http://127.0.0.1:{self.port}",
            },
        )
        self.assertEqual(code, 303)
        self.assertEqual(headers.get("Location"), "/")
        self.assertEqual(len(list_clips(self.registry)), 1)


if __name__ == "__main__":
    unittest.main()
