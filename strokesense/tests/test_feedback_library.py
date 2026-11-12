"""Report discoverability and private asset contracts; synthetic fixtures only."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import feedback


class ReportLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'source.mp4').write_bytes(b'0123456789')
        (self.root / 'first.html').write_text('<h1>First saved analysis</h1>')
        (self.root / 'second.html').write_text('<h1>Detection diagnostic only</h1>')
        self.clips = []
        for cid, title, report, status in [
            ('clip-one', 'First.MOV', 'first.html', 'provisional'),
            ('clip-two', 'Second.mp4', 'second.html', 'unavailable'),
            ('clip-three', 'Missing.MOV', 'missing.html', 'provisional'),
            ('clip-four', 'Not analyzed.MOV', None, 'not_run'),
        ]:
            self.clips.append({'id': cid, 'title': title, 'group_id': 'paired' if cid in ('clip-one','clip-two') else cid,
                'duration': 10., 'video': 'source.mp4', 'report': report,
                'analysis': {'version': 'revision1', 'status': status,
                    'window': {'start': 2., 'end': 8.},
                    'aspects': {k: {'status': 'unavailable', 'summary': 'Synthetic test only.'} for k in feedback.ASPECTS}}})
        (self.root / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'clips': self.clips}))
        self.server = feedback.create_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.origin = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.cookie = None
        self.csrf = json.loads(self.request('GET', '/api/bootstrap')[2])['csrf']

    def stop(self):
        self.server.shutdown(); self.thread.join(3); self.server.server_close()

    def request(self, method, path, data=None, headers=None):
        h = {'Origin': self.origin}
        if self.cookie: h['Cookie'] = self.cookie
        if hasattr(self, 'csrf'): h['X-CSRF-Token'] = self.csrf
        if headers: h.update(headers)
        raw = json.dumps(data) if data is not None else None
        if raw is not None: h['Content-Type'] = 'application/json'
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        c.request(method, path, raw, h)
        r = c.getresponse(); body = r.read(); result = r.status, dict(r.getheaders()), body
        c.close(); return result

    def enroll(self):
        status, h, _ = self.request('POST', '/api/session', {'consent': True, 'role': 'rower', 'experience': '3to5'})
        self.assertEqual(status, 201); self.cookie = h['Set-Cookie'].split(';')[0]

    def test_library_route_has_visible_navigation_and_report_grid(self):
        status, h, body = self.request('GET', '/library')
        self.assertEqual(status, 200, 'Reports library must be directly addressable before consent')
        self.assertIn(b'href="/library"', body)
        self.assertIn(b'id="reports-library"', body)
        self.assertIn(b'id="report-cards"', body)
        self.assertIn(b'id="report-search"', body)
        self.assertEqual(h['Cache-Control'], 'no-store')

    def test_bootstrap_distinguishes_analysis_diagnostic_and_missing_files(self):
        rows = json.loads(self.request('GET', '/api/bootstrap')[2])['clips']
        self.assertEqual([c.get('report_state') for c in rows], ['analysis', 'diagnostic', 'unavailable', 'unavailable'])
        self.assertIn('report', rows[0]['assets'])
        self.assertNotIn('report', rows[2]['assets'], 'Missing report must not advertise a working link')
        self.assertNotIn('source.mp4', json.dumps(rows))
        self.assertNotIn(str(self.root), json.dumps(rows))

    def test_report_links_remain_gated_and_sandboxed(self):
        self.assertEqual(self.request('GET', '/asset/clip-one/report')[0], 401)
        self.enroll()
        for cid, expected in [('clip-one', b'First saved analysis'), ('clip-two', b'Detection diagnostic')]:
            status, h, body = self.request('GET', f'/asset/{cid}/report')
            self.assertEqual(status, 200); self.assertIn(expected, body)
            self.assertIn('sandbox', h['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/asset/clip-three/report')[0], 404)
        (self.root / 'first.html').unlink()
        self.assertEqual(self.request('GET', '/asset/clip-one/report')[0], 404)

    def test_report_navigation_does_not_create_feedback(self):
        self.enroll()
        self.assertEqual(self.request('GET', '/library?clip=clip-two&report=1')[0], 200)
        self.assertEqual(self.request('GET', '/asset/clip-two/report')[0], 200)
        self.assertEqual(self.server.store.rows(), [])
        self.assertEqual(self.request('GET', '/api/owner/export.json')[0], 403)

    def test_old_home_route_and_deep_report_route_share_ui(self):
        home = self.request('GET', '/')[2]
        status, _, deep = self.request('GET', '/library?clip=clip-one&report=1')
        self.assertEqual(status, 200); self.assertEqual(home, deep)
        self.assertEqual(self.request('GET', '/library', headers={'Origin': 'https://foreign.example'})[0], 403)


if __name__ == '__main__': unittest.main()
