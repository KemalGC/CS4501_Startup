"""Loopback blade-mode UI and real private-video decode, with fake model output."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.library import create_server
from strokesense.registry import register_clip, revoke_clip


class BladeWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.video = self.root/'synthetic.avi'
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (128, 96))
        self.assertTrue(writer.isOpened())
        for i in range(120): writer.write(np.full((96, 128, 3), 60 + i % 40, np.uint8))
        writer.release(); self.db = self.root/'clips.db'
        self.cid = register_clip(self.video, self.db, permission='granted', provenance='Synthetic test')[0]['clip_id']
        self.seen = []
        def analyze(path, *, out_dir, selection=None):
            self.seen.append(selection)
            report = out_dir/'report.html'; report.write_text('Synthetic test only')
            return {'report': report}
        self.jobs = JobQueue(registry_db=self.db, job_db=self.root/'jobs.db', results_root=self.root/'results', analyze_fn=analyze)
        self.addCleanup(self.jobs.close)
        self.server = create_server(self.jobs, registry_db=self.db, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start(); self.addCleanup(self.stop)
        self.origin = f'http://127.0.0.1:{self.server.server_address[1]}'
    def stop(self):
        self.server.shutdown(); self.thread.join(3); self.server.server_close()
    def request(self, method, path, data=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        body = None if data is None else urlencode(data)
        headers = {'Origin': origin or self.origin}
        if body is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
        conn.request(method, path, body, headers); r = conn.getresponse(); b = r.read(); h = dict(r.getheaders()); conn.close()
        return r.status, h, b
    def form(self):
        return {'clip': self.cid, 'csrf': self.server.csrf_token, 'seconds': '1.0', 'x': '.3', 'y': '.6', 'confirm': 'yes'}
    def test_library_offers_separate_model_mode_and_manual_reference_controls(self):
        self.assertIn(b'Model-only blade rate', self.request('GET', '/library')[2])
        status, headers, body = self.request('GET', '/blade?clip='+self.cid+'&seconds=1')
        self.assertEqual(status, 200)
        self.assertIn(b'id="blade-canvas"', body)
        self.assertIn(b'name="x"', body); self.assertIn(b'name="y"', body)
        self.assertIn(b'Experimental', body)
        self.assertEqual(self.jobs.list_recent(), [])
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
    def test_confirmation_persists_reference_without_eight_person_requirement(self):
        with patch.dict(os.environ, {'STROKESENSE_BLADE_MODEL': 'test-local:1'}):
            status, headers, _ = self.request('POST', '/blade', self.form())
        self.assertEqual(status, 303)
        job_id = headers['Location'].rsplit('/', 1)[-1]
        self.jobs.wait(job_id, timeout=5)
        self.assertEqual(self.seen[0]['version'], 3)
        self.assertEqual(self.jobs.selection(job_id)['point'], [.3, .6])
    def test_missing_configuration_and_foreign_requests_cannot_enqueue(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.request('POST', '/blade', self.form())[0], 503)
        with patch.dict(os.environ, {'STROKESENSE_BLADE_MODEL': 'test-local:1'}):
            self.assertEqual(self.request('POST', '/blade', dict(self.form(), csrf='bad'))[0], 403)
            self.assertEqual(self.request('POST', '/blade', self.form(), origin='http://foreign.example')[0], 403)
            self.assertEqual(self.request('POST', '/blade', dict(self.form(), confirm='no'))[0], 422)
        self.assertEqual(self.jobs.list_recent(), [])
    def test_revoked_or_changed_source_cannot_be_previewed(self):
        revoke_clip(self.cid, self.db)
        self.assertEqual(self.request('GET', '/blade?clip='+self.cid)[0], 403)
    def test_real_decode_and_model_double_build_no_heuristic_scores(self):
        from strokesense.blade_video import analyse_video
        class ModelDouble:
            def check(self): return {'name': 'test-double', 'digest': 'a'*64}
            def predict(self, reference, frames):
                return [{'frame_id': f['frame_id'], 'time': f['time'], 'same_blade': True,
                         'state': 'air' if f['frame_id'] % 20 < 10 else 'water'} for f in frames]
        chosen = {'version': 3, 'kind': 'blade_reference', 'reference_seconds': 0.,
                  'point': [.3, .6], 'confirmed_same_boat': True}
        result = analyse_video(self.video, out_dir=self.root/'model-results', selection=chosen, provider=ModelDouble(), log=lambda _: None)
        data = json.loads((result['report'].parent/'metrics.json').read_text())
        self.assertAlmostEqual(data['blade_rate']['spm'], 30)
        self.assertEqual(data['blade_rate']['cycles'], 5)
        self.assertEqual(data['rowers'], [])
        self.assertEqual(data['coaching_state'], 'withheld')
        self.assertNotIn('score', data)
        body = result['report'].read_text()
        self.assertIn('not accuracy-validated', body)
        self.assertIn('data:image/jpeg;base64', body)


if __name__ == '__main__': unittest.main()
