"""Real loopback upload failures and recovery; synthetic media, no model calls."""
import contextlib
import io
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_upload as fixture
from strokesense.registry import RegistryError, list_clips, revoke_clip


class UploadFeedbackTests(unittest.TestCase):
    setUp = fixture.UploadHTTPTests.setUp
    stop = fixture.UploadHTTPTests.stop
    request = fixture.UploadHTTPTests.request
    upload = fixture.UploadHTTPTests.upload

    def snapshot(self):
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT * FROM clips ORDER BY clip_id').fetchall()

    def test_duplicate_provenance_has_explicit_nonmutating_selection_recovery(self):
        original = 'PRIVATE-first-attestation'
        supplied = '<script>PRIVATE-new-attestation</script>'
        self.assertEqual(self.upload(provenance=original)[0], 303)
        before = self.snapshot()
        record = list_clips(self.db, show_paths=True)[0]
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            code, headers, body = self.upload(
                provenance=supplied,
                extras=(('analyze', 'now'), ('select_crew', 'yes')),
            )
        self.assertEqual(code, 422)
        self.assertIn(b'Video already in your library', body)
        self.assertIn(b'permission source differs', body)
        self.assertIn(b'Choose rowers for saved clip', body)
        self.assertIn(('/select?clip=' + record['clip_id']).encode(), body)
        self.assertIn('duplicate_provenance', log.getvalue())
        for secret in (original, supplied, str(self.root), self.server.csrf_token):
            self.assertNotIn(secret.encode(), body)
            self.assertNotIn(secret, log.getvalue())
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)
        self.assertEqual(Path(record['source_path']).read_bytes(), fixture.SYNTHETIC_MP4)
        self.assertEqual(self.worker.list_recent(), [])
        with patch('strokesense.web.preview_jpeg', return_value='data:image/jpeg;base64,c3ludGhldGlj'):
            self.assertEqual(self.request('GET', '/select?clip=' + record['clip_id'])[0], 200)

    def test_duplicate_camera_explains_conflict_without_overwriting_saved_metadata(self):
        self.assertEqual(self.upload()[0], 303)
        before = self.snapshot()
        code, _, body = self.upload(extras=(('camera', 'side-on'),))
        self.assertEqual(code, 422)
        self.assertIn(b'camera viewpoint differs', body)
        self.assertIn(b'Choose rowers for saved clip', body)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(list_clips(self.db)[0]['camera'])
        self.assertEqual(len(list(self.uploads.iterdir())), 1)

    def test_422_field_reasons_are_actionable_and_allowlisted(self):
        cases = (
            ({'permission': ''}, 'permission_required', b'Confirm that you have permission'),
            ({'provenance': '  '}, 'provenance_required', b'Enter a permission source'),
            ({'provenance': 'X' * 257}, 'provenance_too_long', b'256 characters'),
            ({'extras': (('camera', 'PRIVATE-invalid-camera'),)}, 'invalid_camera', b'Choose a supported camera viewpoint'),
            ({'data': b''}, 'empty_video', b'The selected file is empty'),
        )
        for kwargs, reason, message in cases:
            with self.subTest(reason=reason):
                log = io.StringIO()
                with contextlib.redirect_stderr(log):
                    code, _, body = self.upload(**kwargs)
                self.assertEqual(code, 422)
                self.assertIn(message, body)
                self.assertIn(reason, log.getvalue())
                self.assertIn(b'Back to import', body)
                self.assertNotIn(b'PRIVATE-invalid-camera', body)
                self.assertNotIn('PRIVATE-invalid-camera', log.getvalue())
        self.assertEqual(list_clips(self.db), [])
        self.assertFalse(self.uploads.exists() and any(self.uploads.iterdir()))

    def test_revoked_duplicate_does_not_regrant_or_offer_recovery(self):
        self.assertEqual(self.upload()[0], 303)
        record = list_clips(self.db)[0]
        revoke_clip(record['clip_id'], self.db)
        before = self.snapshot()
        code, _, body = self.upload(provenance='new statement')
        self.assertEqual(code, 422)
        self.assertIn(b'permission is not granted', body)
        self.assertNotIn(b'/select?clip=', body)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(list(self.uploads.iterdir())), 1)
        self.assertEqual(self.worker.list_recent(), [])

    def test_unknown_registry_error_never_echoes_exception_or_offers_clip(self):
        sensitive = '/private/location SECRET-token'
        log = io.StringIO()
        with patch('strokesense.web.register_clip', side_effect=RegistryError(sensitive)), contextlib.redirect_stderr(log):
            code, _, body = self.upload()
        self.assertEqual(code, 422)
        self.assertIn(b'could not be registered', body)
        self.assertIn('registry_rejected', log.getvalue())
        self.assertNotIn(sensitive.encode(), body)
        self.assertNotIn(sensitive, log.getvalue())
        self.assertNotIn(b'/select?clip=', body)
        self.assertFalse(any(self.uploads.iterdir()))

    def test_matching_duplicate_remains_idempotent_and_security_checks_unchanged(self):
        self.assertEqual(self.upload()[0], 303)
        before = self.snapshot()
        self.assertEqual(self.upload(filename='another-name.mp4')[0], 303)
        for csrf, headers in (("forged", {}), (self.server.csrf_token, {'Origin': 'https://other.invalid'})):
            body, ct = fixture.multipart(csrf, provenance='changed')
            code, _, response = self.request('POST', '/upload', body, ct, headers=headers)
            self.assertEqual(code, 403)
            self.assertNotIn(b'Choose rowers for saved clip', response)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
