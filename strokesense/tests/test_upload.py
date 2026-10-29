"""Browser upload tests: synthetic bytes, loopback HTTP, no model/provider."""
from __future__ import annotations

import http.client
from pathlib import Path
import tempfile
import threading
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips
from strokesense.web import create_server
from strokesense import web



# Minimal synthetic container headers for HTTP behavior tests only. These are
# NOT decodable videos and do not establish codec safety or inference accuracy.
SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12
SYNTHETIC_MOV = b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 12
SYNTHETIC_AVI = b"RIFF" + (28).to_bytes(4, "little") + b"AVI " + b"\x00" * 24
SYNTHETIC_EBML = b"\x1a\x45\xdf\xa3\x84\x42\x86\x81\x01"

def multipart(csrf, *, permission="granted", provenance="synthetic local attestation",
              filename="practice.mp4", data=SYNTHETIC_MP4, extras=()):
    boundary = "StrokeSenseTestBoundary"
    fields = [("csrf", csrf), ("permission", permission),
              ("provenance", provenance)]
    fields.extend(extras)
    blocks = []
    for key, value in fields:
        blocks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            .encode() + value.encode("utf-8") + b"\r\n"
        )
    blocks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="video"; '
        f'filename="{filename}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
        + data + b"\r\n"
    )
    blocks.append(f'--{boundary}--\r\n'.encode())
    return b"".join(blocks), f"multipart/form-data; boundary={boundary}"


class UploadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "registry.sqlite3"
        self.uploads = self.root / "private_uploads"
        self.worker = JobQueue(
            registry_db=self.db, job_db=self.root / "jobs.sqlite3",
            results_root=self.root / "results",
            analyze_fn=lambda *a, **k: None,
        )
        self.addCleanup(self.worker.close)
        self.server = create_server(
            self.worker, registry_db=self.db, upload_dir=self.uploads, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, content_type=None, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        headers = dict(headers or {})
        if content_type:
            headers["Content-Type"] = content_type
        con.request(method, path, body=body, headers=headers)
        r = con.getresponse()
        data = r.read()
        response = (r.status, dict(r.getheaders()), data)
        con.close()
        return response

    def upload(self, **kwargs):
        body, ct = multipart(self.server.csrf_token, **kwargs)
        return self.request("POST", "/upload", body, ct)

    def test_upload_size_limit_accepts_150_mib_video_plus_form_overhead(self):
        self.assertEqual(web._MAX_VIDEO_BYTES, 150 * 1024 * 1024)
        self.assertGreater(web._MAX_UPLOAD, web._MAX_VIDEO_BYTES)
        self.assertLessEqual(web._MAX_UPLOAD, web._MAX_VIDEO_BYTES + 1024 * 1024)

    def test_oversized_declared_request_rejected_before_reading(self):
        body, ct = multipart(self.server.csrf_token)
        code, _, _ = self.request("POST", "/upload", b"", ct,
                                  headers={"Content-Length": str(152 * 1024 * 1024)})
        self.assertEqual(code, 413)
        self.assertEqual(list_clips(self.db), [])

    def test_homepage_offers_private_video_upload(self):
        code, _, body = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'enctype="multipart/form-data"', body)
        self.assertIn(b'name="video"', body)
        self.assertIn(b'name="provenance"', body)

    def test_valid_upload_creates_private_registered_file(self):
        code, headers, body = self.upload()
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertNotIn(str(self.root).encode(), body)
        records = list_clips(self.db, show_paths=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["permission"], "granted")
        actual = Path(records[0]["source_path"])
        self.assertEqual(actual.read_bytes(), SYNTHETIC_MP4)
        self.assertTrue(actual.is_relative_to(self.uploads))
        self.assertEqual(actual.suffix, ".mp4")
        self.assertNotEqual(actual.name, "practice.mp4")

    def test_same_content_is_deduplicated_without_overwriting(self):
        self.assertEqual(self.upload()[0], 303)
        stored = list_clips(self.db, show_paths=True)[0]["source_path"]
        old_contents = Path(stored).read_bytes()
        self.assertEqual(self.upload(filename="copy.mp4")[0], 303)
        self.assertEqual(len(list_clips(self.db)), 1)
        self.assertEqual(Path(stored).read_bytes(), old_contents)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)

    def test_missing_csrf_has_no_file_or_registration_side_effect(self):
        body, ct = multipart("forged")
        code, _, _ = self.request("POST", "/upload", body, ct)
        self.assertEqual(code, 403)
        self.assertEqual(list_clips(self.db), [])
        self.assertFalse(self.uploads.exists() and any(self.uploads.iterdir()))

    def test_requires_explicit_permission_and_provenance(self):
        for kw in ({"permission": "unverified"}, {"permission": ""},
                   {"provenance": ""}, {"provenance": "   "}):
            with self.subTest(kw=kw):
                code, _, _ = self.upload(**kw)
                self.assertEqual(code, 422)
        self.assertEqual(list_clips(self.db), [])

    def test_reject_unsupported_file_and_empty_video(self):
        self.assertEqual(self.upload(filename="../../malicious.py")[0], 415)
        self.assertEqual(self.upload(data=b"")[0], 422)
        self.assertEqual(list_clips(self.db), [])

    def test_traversal_filename_cannot_control_storage_path(self):
        code, _, _ = self.upload(filename="../../outside.mov", data=SYNTHETIC_MOV)
        self.assertEqual(code, 303)
        dest = Path(list_clips(self.db, show_paths=True)[0]["source_path"])
        self.assertTrue(dest.is_relative_to(self.uploads))
        self.assertNotIn("outside", dest.name)
        self.assertEqual(dest.suffix, ".mov")

    def test_reject_oversized_and_malformed_multipart(self):
        body, ct = multipart(self.server.csrf_token)
        code, _, _ = self.request(
            "POST", "/upload", b"", ct,
            headers={"Content-Length": str(26 * 1024 * 1024)})
        self.assertEqual(code, 413)
        code, _, _ = self.request("POST", "/upload", b"invalid content", ct)
        self.assertEqual(code, 400)
        self.assertEqual(list_clips(self.db), [])

    def test_cross_origin_and_host_protection_apply_to_uploads(self):
        body, ct = multipart(self.server.csrf_token)
        code, _, _ = self.request("POST", "/upload", body, ct,
                                  headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        code, _, _ = self.request("POST", "/upload", body, ct,
                                  headers={"Host": "evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(list_clips(self.db), [])


    def test_rejects_disguised_and_truncated_containers_before_persistence(self):
        invalid = (
            ("renamed text", "practice.mp4", b"this is not video"),
            ("wrong extension", "practice.mp4", SYNTHETIC_AVI),
            ("truncated mp4", "practice.mp4", b"\x00\x00\x00\x08ftyp"),
            ("undersized mp4 box", "practice.mp4", b"\x00\x00\x00\x08ftypisom"),
            ("wrong mov", "practice.mov", SYNTHETIC_EBML),
            ("truncated avi", "practice.avi", b"RIFF\x00\x00\x00\x08"),
            ("wrong avi", "practice.avi", SYNTHETIC_MP4),
            ("truncated webm", "practice.webm", b"\x1a\x45\xdf\xa3"),
            ("wrong mkv", "practice.mkv", SYNTHETIC_MP4),
        )
        for description, filename, blob in invalid:
            with self.subTest(case=description):
                code, _, response = self.upload(filename=filename, data=blob)
                self.assertEqual(code, 415)
                self.assertNotIn(str(self.root).encode(), response)
                self.assertEqual(list_clips(self.db), [])
                self.assertFalse(
                    self.uploads.exists() and any(self.uploads.iterdir())
                )

    def test_plausible_supported_container_headers_remain_eligible(self):
        accepted = (
            ("crew.mp4", SYNTHETIC_MP4),
            ("crew.MP4", SYNTHETIC_MP4),
            ("crew.mov", SYNTHETIC_MOV),
            ("crew.avi", SYNTHETIC_AVI),
            ("crew.mkv", SYNTHETIC_EBML),
            ("crew.webm", SYNTHETIC_EBML),
        )
        for filename, blob in accepted:
            with self.subTest(filename=filename):
                code, _, _ = self.upload(filename=filename, data=blob)
                self.assertEqual(code, 303)


    def test_browser_upload_offers_optional_viewpoint_selector(self):
        code, _, body = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'name="camera"', body)
        for angle in (b'value="side-on"', b'value="bow-on"',
                      b'value="stern-on"', b'value=""'):
            with self.subTest(angle=angle):
                self.assertIn(angle, body)

    def test_empty_camera_choice_preserves_unspecified_legacy_metadata(self):
        code, _, _ = self.upload(extras=(("camera", ""),))
        self.assertEqual(code, 303)
        clips = list_clips(self.db)
        self.assertEqual(len(clips), 1)
        self.assertIsNone(clips[0]["camera"])

    def test_upload_saves_explicit_camera_label_and_displays_it(self):
        code, headers, _ = self.upload(extras=(("camera", "side-on"),))
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        clips = list_clips(self.db)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["camera"], "side-on")
        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"side-on", page)
        self.assertNotIn(str(self.root).encode(), page)
        self.assertNotIn(b"synthetic local attestation", page)

    def test_invalid_camera_label_rejected_before_storage(self):
        for supplied in ("diagonal", "side-on ", "<script>alert(1)</script>"):
            with self.subTest(camera=supplied):
                code, _, _ = self.upload(extras=(("camera", supplied),))
                self.assertEqual(code, 422)
        self.assertEqual(list_clips(self.db), [])
        self.assertFalse(self.uploads.exists() and any(self.uploads.iterdir()))
        code, _, _ = self.upload(extras=(
            ("camera", "side-on"), ("camera", "bow-on"),
        ))
        self.assertEqual(code, 400)
        self.assertEqual(list_clips(self.db), [])

    def test_camera_label_dedup_preserves_existing_clip_metadata(self):
        extras = (("camera", "side-on"),)
        self.assertEqual(self.upload(extras=extras)[0], 303)
        self.assertEqual(self.upload(extras=extras, filename="same.mp4")[0], 303)
        self.assertEqual(len(list_clips(self.db)), 1)
        code, _, _ = self.upload(
            extras=(("camera", "bow-on"),), filename="conflict.mp4",
        )
        self.assertEqual(code, 422)
        self.assertEqual(list_clips(self.db)[0]["camera"], "side-on")
        self.assertEqual(len(list(self.uploads.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
