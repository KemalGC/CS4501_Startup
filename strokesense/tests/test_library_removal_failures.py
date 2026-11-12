"""Additional failure-path regressions for library removal (implementation-era)."""
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_library_removal as fixture
from strokesense.registry import list_clips, register_clip


class LibraryRemovalFailureTests(unittest.TestCase):
    setUp = fixture.LibraryRemovalTests.setUp
    request = fixture.LibraryRemovalTests.request
    upload = fixture.LibraryRemovalTests.upload
    stop = fixture.LibraryRemovalTests.stop
    remove = fixture.LibraryRemovalTests.remove

    def test_database_failure_rolls_back_both_records_and_restores_upload(self):
        job = self.worker.submit(self.clip_id); self.worker.wait(job['job_id'], timeout=3)
        real_connection = self.worker._connection
        class Connection:
            def __init__(self): self.conn = real_connection()
            def execute(self, sql, *args):
                if sql.startswith('DELETE FROM registry.clips'):
                    raise sqlite3.OperationalError('private injected storage failure')
                return self.conn.execute(sql, *args)
            def rollback(self): return self.conn.rollback()
            def commit(self): return self.conn.commit()
            def close(self): return self.conn.close()
        before = self.source.read_bytes()
        with patch.object(self.worker, '_connection', side_effect=Connection):
            code, _, body = self.remove()
        self.assertEqual(code, 503)
        self.assertNotIn(b'private injected', body)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(len(list_clips(self.db)), 1)
        self.assertIsNotNone(self.worker.get(job['job_id']))
        self.assertEqual(list(self.uploads.glob('*.removing')), [])

    def test_locked_upload_rename_does_not_remove_any_records(self):
        with patch('strokesense.library.os.replace', side_effect=PermissionError('private path')):
            code, _, body = self.remove()
        self.assertEqual(code, 503)
        self.assertNotIn(b'private path', body)
        self.assertEqual(len(list_clips(self.db)), 1)
        self.assertTrue(self.source.exists())

    def test_cleanup_failure_is_explicit_after_committed_removal(self):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.name.endswith('.removing'):
                raise PermissionError('private error')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            code, headers, _ = self.remove()
        self.assertEqual(code, 303)
        self.assertEqual(headers['Location'], '/library?removed=1&cleanup=1')
        self.assertEqual(list_clips(self.db), [])
        self.assertEqual(len(list(self.uploads.glob('*.removing'))), 1)
        code, _, body = self.request('GET', headers['Location'])
        self.assertEqual(code, 200)
        self.assertIn(b'could not be erased', body)

    def test_unrelated_job_history_stays_available(self):
        source = self.root/'other.mov'; source.write_bytes(b'other recording')
        other = register_clip(source, self.db, permission='granted', provenance='fixture')[0]
        job = self.worker.submit(other['clip_id']); self.worker.wait(job['job_id'], timeout=3)
        self.assertEqual(self.remove()[0], 303)
        self.assertIsNotNone(self.worker.get(job['job_id']))
        self.assertTrue(source.exists())
        self.assertEqual(list_clips(self.db)[0]['clip_id'], other['clip_id'])

    def test_non_form_and_oversized_removal_requests_do_not_mutate(self):
        self.assertEqual(self.request('POST','/library/remove',b'{}','application/json')[0],415)
        self.assertEqual(self.request('POST','/library/remove',b'x'*4097,
                                     'application/x-www-form-urlencoded')[0],413)
        self.assertEqual(len(list_clips(self.db)),1)
        self.assertTrue(self.source.exists())

    def test_wal_databases_are_not_partially_deleted(self):
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        self.assertEqual(self.remove()[0],503)
        self.assertEqual(len(list_clips(self.db)),1)
        self.assertTrue(self.source.exists())


if __name__ == '__main__':
    unittest.main()
