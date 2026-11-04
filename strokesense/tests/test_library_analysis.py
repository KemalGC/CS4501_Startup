"""Actual HTTP access to ordinary and imported saved analysis cards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_upload as fixture
from test_study_library import make_pack
from strokesense.library import create_server
from strokesense.registry import list_clips, revoke_clip
from strokesense.study_library import import_study_pack, get_saved_analysis


class LibraryAnalysisHTTPTests(unittest.TestCase):
    request = fixture.UploadHTTPTests.request
    stop = fixture.UploadHTTPTests.stop

    def setUp(self):
        with patch.object(fixture, 'create_server', create_server):
            fixture.UploadHTTPTests.setUp(self)
        self.pack, self.catalog = make_pack(self.root)
        self.imported = self.run_import()[0]
        self.prefix = '/library/analyses/' + self.imported['analysis_id']

    def run_import(self):
        return import_study_pack(self.worker, self.pack, upload_dir=self.uploads,
                                 permission_source='private fixture permission')

    def test_library_links_real_saved_outputs_and_escaped_details(self):
        code, headers, body = self.request('GET', '/library')
        self.assertEqual(code, 200)
        self.assertIn(b'Saved code analysis', body)
        self.assertIn(b'Eight \xc2\xb7 side view &lt;test&gt;', body)
        self.assertIn(self.prefix.encode(), body)
        self.assertIn(b'25\xe2\x80\x9335 seconds', body)
        self.assertNotIn(b'private-original-filename', body)
        self.assertNotIn(str(self.root).encode(), body)
        detail = self.request('GET', self.prefix)[2]
        self.assertIn(b'28 SPM provisional', detail)
        self.assertIn(b'Body angles', detail)
        self.assertIn(b'Unavailable', detail)
        for role in ('report', 'metrics', 'annotated', 'video'):
            code, headers, data = self.request('GET', self.prefix + '/' + role)
            self.assertEqual(code, 200, role)
            self.assertEqual(headers['Cache-Control'], 'no-store')
        code, headers, data = self.request('GET', self.prefix + '/report')
        self.assertTrue(headers['Content-Security-Policy'].startswith('sandbox;'))
        self.assertNotIn(b'Manage library', data)

    def test_video_ranges_and_route_boundaries(self):
        original = (self.pack / 'source.mp4').read_bytes()
        code, headers, data = self.request('GET', self.prefix + '/video', headers={'Range': 'bytes=2-7'})
        self.assertEqual((code, data), (206, original[2:8]))
        self.assertEqual(headers['Content-Range'], f'bytes 2-7/{len(original)}')
        for value in ('bytes=-0', 'bytes=1000-', 'bytes=0-1,4-8', 'bogus'):
            self.assertEqual(self.request('GET', self.prefix + '/video', headers={'Range': value})[0], 416)
        self.assertEqual(self.request('GET', self.prefix + '/report?path=/etc/passwd')[0], 400)
        self.assertEqual(self.request('GET', self.prefix + '/unknown')[0], 404)
        self.assertEqual(self.request('GET', self.prefix + '/report', headers={'Host': 'foreign.invalid'})[0], 403)
        self.assertEqual(self.request('GET', self.prefix + '/report', headers={'Origin': 'https://foreign.invalid'})[0], 403)

    def test_missing_and_modified_results_fail_closed(self):
        saved = get_saved_analysis(self.worker, self.imported['analysis_id'])
        report = self.worker._results_root / saved['artifacts']['report']['path']
        report.unlink()
        self.assertIn(b'Report unavailable', self.request('GET', '/library')[2])
        self.assertEqual(self.request('GET', self.prefix + '/report')[0], 409)
        self.assertEqual(self.request('GET', self.prefix)[0], 200)
        report.write_text('tampered')
        self.assertEqual(self.request('GET', self.prefix + '/report')[0], 409)
        source = Path(list_clips(self.db, show_paths=True)[0]['source_path'])
        source.write_bytes(b'changed source')
        self.assertEqual(self.request('GET', self.prefix)[0], 409)
        self.assertEqual(self.request('GET', self.prefix + '/metrics')[0], 409)

    def test_permission_revocation_and_removal_keep_old_urls_invalid_after_reimport(self):
        revoke_clip(self.imported['clip_id'], self.db)
        body = self.request('GET', '/library')[2]
        self.assertNotIn(self.prefix.encode(), body)
        for role in ('', '/report', '/video', '/metrics', '/annotated'):
            self.assertEqual(self.request('GET', self.prefix + role)[0], 403)
        form = urlencode({'csrf': self.server.csrf_token,
                          'clip_id': self.imported['clip_id'], 'confirm': 'remove'}).encode()
        self.assertEqual(self.request('POST', '/library/remove', form,
                                     'application/x-www-form-urlencoded')[0], 303)
        again = self.run_import()[0]
        self.assertNotEqual(again['analysis_id'], self.imported['analysis_id'])
        self.assertEqual(self.request('GET', self.prefix + '/report')[0], 404)
        self.assertEqual(self.request('GET', '/library/analyses/' + again['analysis_id'] + '/report')[0], 200)

    def test_normal_job_report_is_visible_without_reimporting_a_study(self):
        def runner(video, *, out_dir):
            out = out_dir / 'nested-results'
            out.mkdir()
            report = out / 'report.html'
            report.write_text('<h1>Normal analysis report</h1>')
            return {'report': report}
        self.worker._analyze_fn = runner
        job = self.worker.submit(self.imported['clip_id'])
        done = self.worker.wait(job['job_id'], timeout=5)
        self.assertEqual(done['status'], 'succeeded')
        body = self.request('GET', '/library')[2]
        self.assertIn(('/reports/' + job['job_id']).encode(), body)
        self.assertIn(b'Open latest report', body)
        self.assertIn(b'Latest analysis: <strong>Completed', body)
        self.assertIn(b'Separate stroke metrics are unavailable', body)
        self.assertNotIn(('/api/jobs/' + job['job_id'] + '/evidence').encode(), body)
        self.assertEqual(self.request('GET', '/reports/' + job['job_id'])[0], 200)
