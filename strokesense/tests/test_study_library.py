"""Saved analysis import preserves actual bytes, history and registration gates.

Fixtures are deliberate non-decodable bytes. These tests validate storage and
HTTP boundaries, not rowing correctness or video codecs.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips, revoke_clip
from strokesense.study_library import (import_study_pack, list_saved_analyses,
    get_saved_analysis, read_saved_asset, StudyImportError, SavedAnalysisError)


def make_pack(root, *, report=True):
    pack = root / 'private-study'
    pack.mkdir()
    (pack / 'source.mp4').write_bytes(b'fixture original video bytes, not decodable')
    (pack / 'annotated.mp4').write_bytes(b'fixture annotated video bytes, not decodable')
    (pack / 'report.html').write_text('<h1>Actual saved output</h1><p>28 SPM provisional</p>')
    (pack / 'metrics.json').write_text(json.dumps({'rowers': [{'summary': {'rate': 28}}]}))
    catalog = {'schema_version': 1, 'clips': [{'id': 'eight-side-view',
        'title': 'Eight · side view <test>', 'group_id': 'study-source-1',
        'duration': 10.0, 'video': 'source.mp4',
        'provenance': {'source': 'private-original-filename.mov', 'start': 25, 'end': 35},
        'analysis': {'version': 'analysis-v1', 'status': 'provisional',
            'window': {'start': 25, 'end': 35}, 'method': 'Saved fixture output',
            'aspects': {'rate': {'status': 'available', 'summary': '28 SPM provisional',
                'details': [{'label': 'Model seat 1', 'value': '28 SPM'}]},
                'position': {'status': 'unavailable', 'summary': 'Angle unavailable', 'details': []}}}}]}
    if report:
        catalog['clips'][0].update(report='report.html', metrics='metrics.json', annotated='annotated.mp4')
    (pack / 'catalog.json').write_text(json.dumps(catalog))
    return pack, catalog


class StudyLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack, self.catalog = make_pack(self.root)
        self.calls = Mock(side_effect=AssertionError('import must not run inference'))
        self.worker = self.queue()
        self.addCleanup(self.worker.close)
        self.uploads = self.root / 'uploads'

    def queue(self):
        return JobQueue(registry_db=self.root / 'registry.sqlite3',
                        job_db=self.root / 'jobs.sqlite3', results_root=self.root / 'results',
                        analyze_fn=self.calls)

    def run_import(self):
        return import_study_pack(self.worker, self.pack, upload_dir=self.uploads,
                                 permission_source='User-owned private fixture')

    def test_import_is_durable_idempotent_and_never_creates_queue_success(self):
        first = self.run_import()[0]
        self.assertFalse(first['reused'])
        saved = get_saved_analysis(self.worker, first['analysis_id'])
        self.assertEqual(read_saved_asset(self.worker, saved, 'report')[0], (self.pack / 'report.html').read_bytes())
        self.assertEqual(read_saved_asset(self.worker, saved, 'metrics')[0], (self.pack / 'metrics.json').read_bytes())
        second = self.run_import()[0]
        self.assertTrue(second['reused'])
        self.assertEqual(second['analysis_id'], first['analysis_id'])
        self.assertEqual(self.worker.list_recent(), [])
        self.calls.assert_not_called()
        self.worker.close()
        with self.queue() as reloaded:
            data = get_saved_analysis(reloaded, first['analysis_id'])
            shutil.rmtree(self.pack)
            self.assertIn(b'Actual saved output', read_saved_asset(reloaded, data, 'report')[0])
            self.assertEqual(len(list_clips(reloaded._registry_db)), 1)
            self.assertEqual(len(list_saved_analyses(reloaded, [first['clip_id']])[first['clip_id']]), 1)
        with closing(self.worker._connection()) as conn:
            provenance = conn.execute('SELECT provenance_json FROM library_saved_analyses').fetchone()[0]
        self.assertIn('private-original-filename.mov', provenance)
        self.assertNotIn('provenance', saved)

    def test_changed_actual_artifact_creates_new_revision_even_if_version_unchanged(self):
        one = self.run_import()[0]
        (self.pack / 'report.html').write_text('<h1>Different actual output</h1>')
        two = self.run_import()[0]
        self.assertNotEqual(one['analysis_id'], two['analysis_id'])
        old = get_saved_analysis(self.worker, one['analysis_id'])
        self.assertIn(b'Actual saved output', read_saved_asset(self.worker, old, 'report')[0])
        self.assertEqual(len(list_saved_analyses(self.worker, [one['clip_id']])[one['clip_id']]), 2)

    def test_missing_outputs_are_recorded_without_success_or_fabricated_report(self):
        self.catalog['clips'][0].pop('report')
        self.catalog['clips'][0].pop('annotated')
        self.catalog['clips'][0].pop('metrics')
        self.catalog['clips'][0]['analysis']['status'] = 'unavailable'
        (self.pack / 'catalog.json').write_text(json.dumps(self.catalog))
        one = self.run_import()[0]
        saved = get_saved_analysis(self.worker, one['analysis_id'])
        self.assertEqual(saved['artifacts'], {})
        with self.assertRaises(SavedAnalysisError) as error:
            read_saved_asset(self.worker, saved, 'report')
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.worker.list_recent(), [])

    def test_tampering_and_revocation_block_all_saved_assets_and_cannot_regrant(self):
        one = self.run_import()[0]
        saved = get_saved_analysis(self.worker, one['analysis_id'])
        source = Path(list_clips(self.worker._registry_db, show_paths=True)[0]['source_path'])
        original = source.read_bytes()
        source.write_bytes(b'changed bytes')
        for role in ('video', 'report', 'metrics', 'annotated'):
            with self.assertRaises(SavedAnalysisError) as error:
                read_saved_asset(self.worker, saved, role)
            self.assertEqual(error.exception.status, 409)
        with self.assertRaisesRegex(StudyImportError, 'registered_source_changed'):
            self.run_import()
        source.write_bytes(original)
        revoke_clip(one['clip_id'], self.worker._registry_db)
        with self.assertRaises(SavedAnalysisError) as error:
            read_saved_asset(self.worker, saved, 'report')
        self.assertEqual(error.exception.status, 403)
        with self.assertRaisesRegex(StudyImportError, 'registered_permission_blocked'):
            self.run_import()

    def test_file_paths_cannot_escape_pack_or_use_symbolic_links(self):
        outside = self.root / 'outside.html'
        outside.write_text('private file')
        for value in ('../outside.html', str(outside), 'linked.html'):
            if value == 'linked.html':
                (self.pack / value).symlink_to(outside)
            self.catalog['clips'][0]['report'] = value
            (self.pack / 'catalog.json').write_text(json.dumps(self.catalog))
            with self.assertRaises(StudyImportError):
                self.run_import()
            self.assertEqual(list_clips(self.worker._registry_db), [])

    def test_missing_referenced_result_rejects_import_before_registering_source(self):
        (self.pack / 'report.html').unlink()
        with self.assertRaises(StudyImportError):
            self.run_import()
        self.assertEqual(list_clips(self.worker._registry_db), [])
