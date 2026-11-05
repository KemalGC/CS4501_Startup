"""Acceptance tests use fictional approvals and a fake generator, never real reviews."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_validation import trusted_synthetic_fixture


class ReviewDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'private.mp4'
        self.video.write_bytes(b'FICTIONAL TEST MEDIA')
        self.report = self.root / 'report.html'
        self.report.write_text('<h1>Synthetic fixture report</h1>')
        snapshot, self.candidate, self.cues = trusted_synthetic_fixture()
        self.metrics = self.root / 'metrics.json'
        self.metrics.write_text(json.dumps({'evidence': snapshot}))
        self.review = self.root / 'review.json'
        self.manifest = {
            'schema_version': 1,
            'metrics_sha256': hashlib.sha256(self.metrics.read_bytes()).hexdigest(),
            'video_sha256': hashlib.sha256(self.video.read_bytes()).hexdigest(),
            'reviewed_by': 'TEST-ONLY reviewer',
            'reviewed_at': '2026-11-04T12:00:00Z',
            'confirmed_source_and_finding': True,
            'finding_id': self.candidate['finding_id'],
            'eligible_stroke_ids': [x['id'] for x in snapshot['strokes']],
            'cues': self.cues,
        }
        self.save_review()
        self.generator = Mock(return_value=copy.deepcopy(self.candidate))
        self.factory = Mock(return_value=self.generator)

    def save_review(self):
        self.review.write_text(json.dumps(self.manifest))

    def session(self, **kwargs):
        from strokesense.review_demo import CoachingSession
        return CoachingSession(self.video, self.report, self.metrics,
                               review_path=kwargs.pop('review_path', self.review),
                               generator_factory=self.factory,
                               mode=kwargs.pop('mode', 'test_double'), **kwargs)

    def run_session(self, session):
        self.assertTrue(session.begin())
        session.worker.join(5)
        self.assertFalse(session.worker.is_alive())
        return session.snapshot()

    def test_missing_review_withholds_without_constructing_provider(self):
        s = self.session(review_path=None)
        self.assertFalse(s.begin())
        self.assertEqual(s.snapshot()['reason'], 'review_required')
        self.factory.assert_not_called()

    def test_live_mode_requires_explicit_opt_in(self):
        s = self.session(mode='disabled')
        self.assertFalse(s.begin())
        self.assertEqual(s.snapshot()['reason'], 'live_not_enabled')
        self.factory.assert_not_called()

    def test_valid_review_and_candidate_produce_source_linked_draft(self):
        result = self.run_session(self.session())
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(result['mode'], 'test_double')
        self.assertEqual(result['candidate'], self.candidate)
        self.assertEqual(result['attempts'], 1)
        self.assertIn('free_text_unverified', result['warnings'])
        self.assertEqual(len(result['evidence']), 2)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn('TEST-ONLY reviewer', json.dumps(result))

    def test_changed_source_or_metrics_blocks_generation(self):
        for path in (self.video, self.metrics):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                s = self.session()
                self.assertFalse(s.begin())
                self.assertEqual(s.snapshot()['reason'], 'review_source_mismatch')
                path.write_bytes(original)
        self.factory.assert_not_called()

    def test_review_must_cover_the_actual_finding_and_eligible_strokes(self):
        for key, value in [('finding_id', 'invented'),
                           ('eligible_stroke_ids', ['invented']),
                           ('confirmed_source_and_finding', False),
                           ('reviewed_by', ''), ('reviewed_at', 'yesterday')]:
            with self.subTest(key=key):
                prior = copy.deepcopy(self.manifest)
                self.manifest[key] = value
                self.save_review()
                self.assertFalse(self.session().begin())
                self.manifest = prior
        self.factory.assert_not_called()

    def test_correction_rejects_wrong_quantity_then_accepts(self):
        bad = copy.deepcopy(self.candidate)
        bad['observed_count'] = 99
        self.generator.side_effect = [bad, self.candidate]
        result = self.run_session(self.session())
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(result['attempts'], 2)
        self.assertIn('incorrect_quantity', self.generator.call_args_list[1].args[1])

    def test_three_invalid_candidates_are_withheld_without_leaking_text(self):
        bad = copy.deepcopy(self.candidate)
        bad['stroke_ids'] = ['invented']
        bad['explanation'] = 'PRIVATE REJECTED TEXT'
        self.generator.return_value = bad
        result = self.run_session(self.session())
        self.assertEqual(result['state'], 'withheld')
        self.assertEqual(result['attempts'], 3)
        self.assertIsNone(result['candidate'])
        self.assertNotIn('PRIVATE REJECTED TEXT', json.dumps(result))

    def test_provider_failure_is_sanitized_and_not_retried(self):
        self.factory.side_effect = RuntimeError('PRIVATE API KEY AND PATH')
        result = self.run_session(self.session())
        self.assertEqual(result['state'], 'withheld')
        self.assertNotIn('PRIVATE API', json.dumps(result))
        self.factory.assert_called_once()

    def test_duplicate_click_cannot_cause_another_model_run(self):
        s = self.session()
        self.run_session(s)
        self.assertFalse(s.begin())
        self.factory.assert_called_once()

    def test_recheck_source_after_page_load_and_before_request(self):
        s = self.session()
        self.video.write_bytes(b'CHANGED SOURCE')
        self.assertFalse(s.begin())
        self.factory.assert_not_called()

    def test_review_packet_starts_unapproved(self):
        from strokesense.review_demo import review_template
        template = review_template(self.video, self.metrics)
        self.assertFalse(template['confirmed_source_and_finding'])
        self.assertEqual(template['reviewed_by'], '')
        self.assertEqual(template['cues'], {})
        self.assertIn('findings_for_review', template)

    def test_oversized_review_is_rejected_before_loading(self):
        self.review.write_bytes(b' ' * (256 * 1024 + 1))
        self.assertFalse(self.session().begin())
        self.factory.assert_not_called()

    def start_server(self, session):
        from strokesense.review_demo import create_server
        server = create_server(session, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        return server, f'http://127.0.0.1:{server.server_address[1]}'

    def request(self, base, path='/', *, method='GET', headers=None, body=None):
        try:
            with urlopen(Request(base + path, data=body, method=method,
                                 headers=headers or {}), timeout=5) as r:
                return r.status, r.read(), dict(r.headers)
        except HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_browser_routes_connect_clip_report_evidence_and_llm_result(self):
        s = self.session()
        server, base = self.start_server(s)
        code, page, _ = self.request(base)
        self.assertEqual(code, 200)
        self.assertIn(b'Generate coaching draft', page)
        self.assertIn(b'/video', page)
        self.assertIn(b'/report', page)
        self.assertIn(b'Test double', page)
        self.assertEqual(self.request(base, '/report')[0], 200)
        code, body, _ = self.request(base, '/video', headers={'Range': 'bytes=0-3'})
        self.assertEqual((code, body), (206, b'FICT'))
        headers = {'Origin': base, 'X-CSRF-Token': server.csrf,
                   'Content-Type': 'application/json'}
        self.assertEqual(self.request(base, '/api/coaching', method='POST',
                                     headers=headers, body=b'{}')[0], 202)
        s.worker.join(5)
        result = json.loads(self.request(base, '/api/status')[1])
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(result['candidate'], self.candidate)
        self.assertEqual(self.request(base, '/api/coaching', method='POST',
                                     headers=headers, body=b'{}')[0], 409)

    def test_cross_origin_csrf_host_and_unknown_paths_cannot_generate(self):
        server, base = self.start_server(self.session())
        for headers in ({}, {'Origin': 'https://other.example',
                             'X-CSRF-Token': server.csrf}):
            self.assertEqual(self.request(base, '/api/coaching', method='POST',
                                         headers=headers, body=b'{}')[0], 403)
        self.assertEqual(self.request(base, headers={'Host': 'other.example'})[0], 403)
        self.assertEqual(self.request(base, '/private/metrics.json')[0], 404)
        self.factory.assert_not_called()

    def test_report_is_sandboxed_and_model_text_uses_text_content(self):
        _, base = self.start_server(self.session())
        _, _, headers = self.request(base, '/report')
        self.assertIn('sandbox', headers['Content-Security-Policy'])
        _, page, _ = self.request(base)
        self.assertIn(b'textContent', page)
        self.assertNotIn(b'innerHTML', page)


if __name__ == '__main__':
    unittest.main()
