"""Technical review contracts using synthetic clips and synthetic participant data."""
from copy import deepcopy
import csv
import io
import json
import threading
import unittest
import test_feedback as fixture


class FeedbackEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.FeedbackTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        from strokesense.feedback_evaluation import QUESTIONS, VERSION
        self.questions = QUESTIONS
        self.version = VERSION

    def payload(self):
        return {'clip_id': 'clip-one', 'analysis_version': self.base.clip['analysis']['version'],
                'questionnaire_version': self.version,
                'answers': {key: {'verdict': 'correct', 'timestamp_seconds': None, 'comment': ''}
                            for key in self.questions}, 'stroke_measurement': None,
                'comment': 'Synthetic technical assessment'}

    def measurement(self):
        return {'catch_count': 5, 'first_catch_seconds': 0., 'last_catch_seconds': 8.,
                'rower_reference': 'Synthetic seat one'}

    def save(self, payload=None):
        return self.base.request('POST', '/api/evaluation', self.payload() if payload is None else payload)

    def get(self):
        code, _, body = self.base.request('GET', '/api/evaluation?clip=clip-one')
        self.assertEqual(code, 200)
        return json.loads(body)['responses']

    def owner(self, ext='json'):
        return self.base.request('GET', '/api/owner/evaluation.'+ext,
                                 headers={'Authorization': 'Bearer '+self.base.server.owner_key})

    def restart(self):
        self.base.stop()
        (self.base.root/'catalog.json').write_text(json.dumps({'schema_version': 1, 'clips': [self.base.clip]}))
        self.base.server = self.base.f.create_server(self.base.root, port=0)
        self.base.thread = threading.Thread(target=self.base.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.base.thread.start()
        self.base.port = self.base.server.server_address[1]
        self.base.origin = f'http://127.0.0.1:{self.base.port}'
        _, _, body = self.base.request('GET', '/api/bootstrap')
        self.base.csrf = json.loads(body)['csrf']

    def test_bootstrap_adds_ten_criteria_preserving_existing_questionnaires(self):
        _, _, body = self.base.request('GET', '/api/bootstrap')
        data = json.loads(body)
        self.assertEqual(data['evaluation_version'], 'technical-v1')
        self.assertEqual([q['id'] for q in data['evaluation_questions']], list(self.questions))
        self.assertEqual(len(data['evaluation_questions']), 10)
        self.assertEqual(len(data['aspects']), 6)
        self.assertEqual(len(data['quality_questions']), 5)
        self.assertIn('coxswain', data['evaluation_questions'][0]['question'])

    def test_static_assets_and_form_are_served_with_self_only_scripts(self):
        code, headers, html = self.base.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'id="evaluation-form"', html)
        self.assertIn(b'/evaluation.js', html)
        self.assertIn('study’s database'.encode(), html)
        self.assertNotIn(b'stored on this device', html)
        self.assertNotIn(b'stored locally', html)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        for path in ('/evaluation.js', '/evaluation.css'):
            self.assertEqual(self.base.request('GET', path)[0], 200)

    def test_session_csrf_same_origin_and_owner_export_protection(self):
        self.assertEqual(self.save()[0], 401)
        self.assertEqual(self.base.request('GET', '/api/evaluation?clip=clip-one')[0], 401)
        self.base.enroll()
        self.assertEqual(self.base.request('POST', '/api/evaluation', self.payload(), {'X-CSRF-Token': 'bad'})[0], 403)
        self.assertEqual(self.base.request('POST', '/api/evaluation', self.payload(), {'Origin': 'https://foreign.example'})[0], 403)
        for ext in ('json', 'csv'):
            self.assertEqual(self.base.request('GET', '/api/owner/evaluation.'+ext)[0], 403)

    def test_save_restore_edit_and_server_restart_preserve_one_assessment(self):
        self.base.enroll()
        data = self.payload()
        data['answers']['evidence_alignment'].update(verdict='partly_correct', timestamp_seconds=2.75, comment='Synthetic evidence correction')
        self.assertEqual(self.save(data)[0], 200)
        original = self.get()[0]
        data['answers']['stroke_rate']['verdict'] = 'cannot_judge'
        self.assertEqual(self.save(data)[0], 200)
        self.restart()
        rows = self.get()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['created_utc'], original['created_utc'])
        self.assertEqual(rows[0]['answers'], data['answers'])
        self.assertEqual(rows[0]['assessment_type'], 'human_perceived_assessment')
        _, _, body = self.base.request('GET', '/api/owner/summary', headers={'Authorization': 'Bearer '+self.base.server.owner_key})
        self.assertEqual(json.loads(body)['technical_evaluation']['assessment_count'], 1)

    def test_new_analysis_revision_keeps_old_feedback_separate(self):
        self.base.enroll()
        self.assertEqual(self.save()[0], 200)
        old = self.payload()
        self.base.clip['analysis']['version'] = 'revision2'
        self.restart()
        self.assertEqual(self.save(old)[0], 422)
        self.assertEqual(self.save()[0], 200)
        self.assertEqual({r['analysis_version'] for r in self.get()}, {'revision1', 'revision2'})

    def test_invalid_revision_questionnaire_clip_and_top_level_fields(self):
        self.base.enroll()
        for key, value in [('analysis_version', 'stale'), ('questionnaire_version', 'technical-v2'), ('reviewer_id', 'someone-else')]:
            with self.subTest(key=key):
                data = self.payload();data[key] = value
                self.assertEqual(self.save(data)[0], 422)
        data = self.payload();data['clip_id'] = 'other-clip'
        self.assertEqual(self.save(data)[0], 404)
        self.assertEqual(self.get(), [])

    def test_requires_exact_criteria_and_strict_verdicts(self):
        self.base.enroll()
        for value in [True, 0, 1, None, [], {}, 'wrong', 'CORRECT']:
            with self.subTest(value=value):
                data = self.payload();data['answers']['stroke_rate']['verdict'] = value
                self.assertEqual(self.save(data)[0], 422)
        for change in ('missing', 'extra', 'answer_extra', 'answer_missing'):
            data = self.payload()
            if change == 'missing':del data['answers']['stroke_rate']
            elif change == 'extra':data['answers']['unknown'] = deepcopy(data['answers']['stroke_rate'])
            elif change == 'answer_extra':data['answers']['stroke_rate']['score'] = 5
            else:del data['answers']['stroke_rate']['comment']
            self.assertEqual(self.save(data)[0], 422)
        self.assertEqual(self.get(), [])

    def test_unjudgeable_and_inapplicable_remain_distinct_unscored_answers(self):
        self.base.enroll()
        data = self.payload()
        data['answers']['stroke_rate']['verdict'] = 'cannot_judge'
        data['answers']['crew_synchrony']['verdict'] = 'not_applicable'
        data['answers']['catch_body_angle']['verdict'] = 'incorrect'
        self.assertEqual(self.save(data)[0], 200)
        _, _, body = self.owner()
        exported = json.loads(body)
        self.assertEqual(exported['summary']['verdict_counts']['cannot_judge'], 1)
        self.assertEqual(exported['summary']['verdict_counts']['not_applicable'], 1)
        self.assertEqual(exported['summary']['verdict_counts']['incorrect'], 1)
        self.assertNotIn('accuracy', exported['summary'])
        self.assertNotIn('score', self.get()[0]['answers']['stroke_rate'])

    def test_unavailable_outputs_cannot_be_judged_correct_partly_or_incorrect(self):
        self.base.enroll()
        self.base.clip['analysis']['aspects']['position']['status'] = 'unavailable'
        self.restart()
        for verdict in ('correct', 'partly_correct', 'incorrect'):
            data = self.payload()
            data['answers']['catch_body_angle']['verdict'] = verdict
            data['answers']['finish_body_angle']['verdict'] = 'not_applicable'
            self.assertEqual(self.save(data)[0], 422)
        data = self.payload()
        data['answers']['catch_body_angle']['verdict'] = 'cannot_judge'
        data['answers']['finish_body_angle']['verdict'] = 'not_applicable'
        self.assertEqual(self.save(data)[0], 200)
        self.assertEqual(self.get()[0]['answers']['uncertainty_handling']['verdict'], 'correct')

    def test_valid_timestamp_boundaries_and_literal_comments_are_preserved(self):
        self.base.enroll()
        data = self.payload()
        data['answers']['subject_identity'].update(timestamp_seconds=0, comment='<script>alert(1)</script>')
        data['answers']['evidence_alignment']['timestamp_seconds'] = 10.
        self.assertEqual(self.save(data)[0], 200)
        self.assertEqual(self.get()[0]['answers']['subject_identity']['comment'], '<script>alert(1)</script>')

    def test_invalid_timestamp_comment_and_nested_shape_rejected_atomically(self):
        self.base.enroll()
        for key, values in [('timestamp_seconds', [True, -1, 10.01, '3', float('nan'), float('inf')]),
                            ('comment', [True, None, 'x'*501, 'bad\x00text'])]:
            for value in values:
                with self.subTest(key=key, value=value):
                    data = self.payload();data['answers']['evidence_alignment'][key] = value
                    self.assertEqual(self.save(data)[0], 422)
        for value in (False, 'x'*2001, 'bad\x00text'):
            data = self.payload();data['comment'] = value
            self.assertEqual(self.save(data)[0], 422)
        self.assertEqual(self.get(), [])

    def test_manual_cadence_uses_catch_intervals_and_is_explicitly_unverified(self):
        self.base.enroll()
        data = self.payload();data['stroke_measurement'] = self.measurement()
        code, _, body = self.save(data)
        self.assertEqual(code, 200)
        measurement = json.loads(body)['stroke_measurement']
        self.assertEqual(measurement['rate_spm'], 30.)
        self.assertEqual(measurement['method'], 'manual_consecutive_catches')
        self.assertIs(measurement['verified_ground_truth'], False)
        self.restart()
        self.assertEqual(self.get()[0]['stroke_measurement'], measurement)

    def test_manual_observation_can_be_removed_on_edit(self):
        self.base.enroll()
        data = self.payload();data['stroke_measurement'] = self.measurement()
        self.assertEqual(self.save(data)[0], 200)
        self.assertEqual(self.save()[0], 200)
        self.assertIsNone(self.get()[0]['stroke_measurement'])

    def test_manual_cadence_rejects_partial_invalid_and_client_computed_values(self):
        self.base.enroll()
        cases = [('catch_count', True), ('catch_count', 1), ('catch_count', 2.5), ('catch_count', 1001),
                 ('first_catch_seconds', None), ('first_catch_seconds', -1), ('first_catch_seconds', 8.),
                 ('last_catch_seconds', 0), ('last_catch_seconds', 11), ('last_catch_seconds', float('nan')),
                 ('rower_reference', ''), ('rower_reference', 'x'*121), ('rower_reference', False),
                 ('rate_spm', 99), ('verified_ground_truth', True)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                data = self.payload();data['stroke_measurement'] = self.measurement();data['stroke_measurement'][key] = value
                self.assertEqual(self.save(data)[0], 422)
        data = self.payload();data['stroke_measurement'] = {'catch_count': 5}
        self.assertEqual(self.save(data)[0], 422)
        self.assertEqual(self.get(), [])

    def test_other_session_cannot_read_edit_or_withdraw_first_reviewers_assessment(self):
        first = self.base.enroll()
        self.assertEqual(self.save()[0], 200)
        first_cookie = self.base.cookie
        self.base.cookie = None;self.base.enroll()
        self.assertEqual(self.get(), [])
        data = self.payload();data['comment'] = 'Synthetic second reviewer'
        self.assertEqual(self.save(data)[0], 200)
        self.base.request('POST', '/api/withdraw', {})
        self.base.cookie = first_cookie
        self.assertEqual(len(self.get()), 1)
        self.assertEqual(self.get()[0]['reviewer_id'], first['reviewer_id'])
        self.assertEqual(self.get()[0]['comment'], 'Synthetic technical assessment')

    def test_withdraw_cascades_all_three_questionnaires(self):
        self.base.enroll()
        self.base.request('POST', '/api/reviews', self.base.review())
        self.base.request('POST', '/api/quality', {'clip_id': 'clip-one', 'analysis_version': 'revision1',
            'questionnaire_version': 'quality-v1', 'comment': 'Synthetic',
            'answers': {key: 'cannot_judge' for key in ('clarity','specificity','completeness','evidence_support','actionability')}})
        self.assertEqual(self.save()[0], 200)
        self.assertEqual(self.base.request('POST', '/api/withdraw', {})[0], 200)
        _, _, body = self.owner()
        self.assertEqual(json.loads(body)['responses'], [])
        self.assertEqual(self.base.server.store.rows(), [])
        from strokesense.feedback_quality import QualityStore
        self.assertEqual(QualityStore(self.base.server.store).rows(), [])

    def test_owner_csv_keeps_versions_skips_evidence_measurements_and_escapes_formulas(self):
        self.base.enroll()
        data = self.payload();data['comment'] = '=2+2'
        data['answers']['stroke_rate'].update(verdict='cannot_judge', timestamp_seconds=2.5, comment='+formula')
        data['stroke_measurement'] = dict(self.measurement(), rower_reference='@seat1')
        self.assertEqual(self.save(data)[0], 200)
        code, _, body = self.owner('csv');self.assertEqual(code, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 10)
        rate = next(row for row in rows if row['criterion_id'] == 'stroke_rate')
        self.assertEqual(rate['questionnaire_version'], 'technical-v1')
        self.assertEqual(rate['analysis_version'], 'revision1')
        self.assertEqual(rate['verdict'], 'cannot_judge')
        self.assertEqual(rate['timestamp_seconds'], '2.5')
        self.assertEqual(rate['manual_rate_spm'], '30.0')
        self.assertEqual(rate['manual_rower_reference'], "'@seat1")
        self.assertEqual(rate['criterion_comment'], "'+formula")
        self.assertEqual(rate['comment'], "'=2+2")

    def test_install_and_technical_save_preserve_original_aspect_responses(self):
        self.base.enroll()
        self.base.request('POST', '/api/reviews', self.base.review())
        original = self.base.server.store.rows()
        from strokesense.feedback_evaluation import EvaluationStore
        EvaluationStore(self.base.server.store)
        self.assertEqual(self.save()[0], 200)
        self.restart()
        self.assertEqual(self.base.server.store.rows(), original)

    def test_get_rejects_missing_duplicate_and_unknown_clip_queries(self):
        self.base.enroll()
        for path in ('/api/evaluation', '/api/evaluation?other=clip-one', '/api/evaluation?clip=clip-one&clip=clip-one'):
            self.assertEqual(self.base.request('GET', path)[0], 400)
        self.assertEqual(self.base.request('GET', '/api/evaluation?clip=missing')[0], 404)


if __name__ == '__main__':
    unittest.main()
