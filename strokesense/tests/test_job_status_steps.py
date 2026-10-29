"""Loopback route tests for a truthful accessible Alpha job-stage UI.

All statuses and sources are synthetic; no real inference is performed.
"""
from __future__ import annotations

import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


class JobStatusStagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        media = root / 'privately-owned.mov'
        media.write_bytes(b'synthetic fixture, not real footage')
        self.registry = root / 'registry.sqlite3'
        self.clip_id = register_clip(media, self.registry, permission='granted',
                                     provenance='synthetic test consent')[0]['clip_id']
        self.jobs = JobQueue(registry_db=self.registry, job_db=root / 'jobs.sqlite3',
                             results_root=root / 'results', analyze_fn=lambda *a, **k: None)
        self.addCleanup(self.jobs.close)
        self.server = create_server(self.jobs, registry_db=self.registry, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.job_id = 'a' * 32

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, path):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=3)
        connection.request('GET', path)
        response = connection.getresponse()
        code, headers, body = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return code, headers, body.decode('utf-8')

    def route(self, status, *, api=False, error=None):
        record = {'job_id': self.job_id, 'clip_id': self.clip_id, 'status': status,
                  'coaching_state': 'withheld', 'error_code': error}
        with patch.object(self.jobs, 'get', return_value=record), patch.object(
                self.jobs, 'media_artifact', return_value=None):
            return self.request(f'/api/jobs/{self.job_id}' if api else f'/jobs/{self.job_id}')

    def test_queued_running_and_success_stages_are_truthful(self):
        for status, expected_current, expected_completed in (
            ('queued', 'Queued', 0), ('running', 'Analyzing', 1),
            ('succeeded', None, 3),
        ):
            with self.subTest(status=status):
                code, headers, html = self.route(status)
                self.assertEqual(code, 200)
                self.assertIn('<ol class="job-steps" aria-label="Analysis stages">', html)
                self.assertEqual(html.count('class="job-step is-complete"'), expected_completed)
                self.assertIn('Results', html)
                if expected_current:
                    self.assertRegex(html, r'(?s)<li class="job-step is-current" aria-current="step">.*?' + expected_current + '</span>')
                else:
                    self.assertNotIn('aria-current="step"', html)
                self.assertNotIn('% complete', html)
                self.assertNotIn('synthetic test consent', html)
                self.assertIn('prefers-reduced-motion', html)
                self.assertIn('@media (max-width: 720px)', html)
                if status in ('queued', 'running'):
                    self.assertIn('<meta http-equiv="refresh" content="2">', html)
                else:
                    self.assertNotIn('<meta http-equiv="refresh" content="2">', html)

    def test_failed_job_does_not_claim_results_ready(self):
        code, _, html = self.route('failed', error='analysis_failed')
        self.assertEqual(code, 200)
        self.assertIn('Results unavailable', html)
        self.assertIn('Processing stopped', html)
        self.assertNotIn('Results available', html)
        self.assertNotIn('aria-current="step"', html)
        self.assertIn('Retry analysis', html)
        self.assertNotIn('<meta http-equiv="refresh" content="2">', html)

    def test_status_api_remains_read_only_json_without_html(self):
        code, headers, body = self.route('running', api=True)
        self.assertEqual(code, 200)
        self.assertIn('application/json', headers['Content-Type'])
        self.assertIn('"status": "running"', body)
        self.assertNotIn('job-steps', body)


if __name__ == '__main__':
    unittest.main()
