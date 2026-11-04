"""Revision-bound technical judgments and explicitly manual cadence observations.

These answers are participant perceptions. A manually counted cadence is a
reviewer measurement, not an adjudicated benchmark or model-accuracy label.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import csv
import io
import json
import math

VERSION = 'technical-v1'
VERDICTS = ('correct', 'partly_correct', 'incorrect', 'cannot_judge', 'not_applicable')
JUDGED = frozenset(VERDICTS[:3])
QUESTIONS = {
    'subject_identity': ('Eight, seats and rower identity', 'Does the output follow the same eight, identify all eight rowing seats where visible, exclude the coxswain, and retain the correct rower identities throughout?', 'tracking'),
    'stroke_rate': ('Stroke rate', 'Does the reported strokes per minute match repeated catches by the same rower during the analyzed window?', 'rate'),
    'catch_body_angle': ('Body angle at the catch', 'Does the catch body-angle claim match the visible trunk position at the actual catch, allowing for camera perspective?', 'position'),
    'finish_body_angle': ('Body angle at the finish', 'Does the finish body-angle claim match the visible trunk position at the actual finish, allowing for camera perspective?', 'position'),
    'drive_sequence': ('Drive sequence', 'Do claims about legs, body swing and arms during the drive match the visible movement?', 'sequencing'),
    'recovery_sequence': ('Recovery sequence', 'Do claims about hands away, body preparation and slide during recovery match the visible movement?', 'sequencing'),
    'crew_synchrony': ('Crew timing', 'Do the reported early or late rowers and catch differences match the same strokes you can see?', 'timing'),
    'evidence_alignment': ('Evidence matches the claim', 'Do timestamps, highlighted rowers, snapshots and curves show the exact movement described, with enough context to check it?', 'evidence'),
    'actionable_specificity': ('Specific, usable advice', 'Does the advice clearly identify a visible issue and a practical next step for this rower or crew?', 'evidence'),
    'uncertainty_handling': ('Limits and uncertainty', 'Does the report acknowledge hidden joints, poor views, boat changes or too few strokes, and withhold claims the video cannot support?', None),
}
FIELDS = ['reviewer_id', 'role', 'experience', 'clip_id', 'analysis_version', 'questionnaire_version',
          'assessment_type', 'criterion_id', 'verdict', 'timestamp_seconds', 'criterion_comment',
          'manual_catch_count', 'manual_first_catch_seconds', 'manual_last_catch_seconds',
          'manual_rate_spm', 'manual_rower_reference', 'measurement_method', 'comment',
          'created_utc', 'updated_utc']
METHOD = 'Participant judgments; manual cadence uses consecutive catches of one rower. Neither is an adjudicated model-accuracy benchmark.'


def public_questions():
    return [{'id': key, 'title': title, 'question': question, 'aspect_id': aspect}
            for key, (title, question, aspect) in QUESTIONS.items()]


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('comment_too_long_or_invalid')
    return value.strip()


def _stamp(value, duration):
    if value is not None and (not _finite(value) or not 0 <= value <= duration):
        raise ValueError('timestamp_outside_video')
    return value


def validate_evaluation(data, clip):
    required = {'clip_id', 'analysis_version', 'questionnaire_version', 'answers', 'stroke_measurement', 'comment'}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError('invalid_evaluation_fields')
    if data['clip_id'] != clip['id'] or data['analysis_version'] != clip['analysis']['version']:
        raise ValueError('analysis_changed_reload')
    if data['questionnaire_version'] != VERSION:
        raise ValueError('evaluation_version_changed_reload')
    answers = data['answers']
    if not isinstance(answers, dict) or set(answers) != set(QUESTIONS):
        raise ValueError('all_ten_technical_answers_required')
    validated = {}
    for key, value in answers.items():
        if not isinstance(value, dict) or set(value) != {'verdict', 'timestamp_seconds', 'comment'}:
            raise ValueError('invalid_criterion_fields')
        verdict = value['verdict']
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            raise ValueError('invalid_technical_verdict')
        aspect = QUESTIONS[key][2]
        if aspect and clip['analysis']['aspects'][aspect].get('status', 'unavailable') in ('unavailable', 'not_run') and verdict in JUDGED:
            raise ValueError('no_output_to_judge_for_criterion')
        validated[key] = {'verdict': verdict, 'timestamp_seconds': _stamp(value['timestamp_seconds'], clip['duration']),
                          'comment': _text(value['comment'], 500)}
    measurement = data['stroke_measurement']
    if measurement is not None:
        fields = {'catch_count', 'first_catch_seconds', 'last_catch_seconds', 'rower_reference'}
        if not isinstance(measurement, dict) or set(measurement) != fields:
            raise ValueError('invalid_stroke_measurement_fields')
        count = measurement['catch_count']
        if type(count) is not int or not 2 <= count <= 1000:
            raise ValueError('catch_count_must_be_2_to_1000')
        start = _stamp(measurement['first_catch_seconds'], clip['duration'])
        end = _stamp(measurement['last_catch_seconds'], clip['duration'])
        if start is None or end is None or end <= start:
            raise ValueError('last_catch_must_follow_first')
        # N visible catches delimit N-1 complete stroke intervals. The client
        # cannot supply or override the derived rate.
        try:
            rate = 60.0 * (count - 1) / (end - start)
        except (OverflowError, ZeroDivisionError):
            raise ValueError('invalid_stroke_interval') from None
        if not math.isfinite(rate):
            raise ValueError('invalid_stroke_interval')
        reference = _text(measurement['rower_reference'], 120)
        if not reference:
            raise ValueError('rower_reference_required')
        measurement = {'catch_count': count, 'first_catch_seconds': start, 'last_catch_seconds': end,
                       'rower_reference': reference, 'rate_spm': rate,
                       'method': 'manual_consecutive_catches', 'verified_ground_truth': False}
    return {'clip_id': clip['id'], 'analysis_version': clip['analysis']['version'],
            'questionnaire_version': VERSION, 'answers': validated, 'stroke_measurement': measurement,
            'comment': _text(data['comment'], 2000), 'assessment_type': 'human_perceived_assessment'}


class EvaluationStore:
    """One atomic assessment per reviewer, clip, analysis and questionnaire revision."""
    def __init__(self, review_store):
        self.store = review_store
        with closing(self.store.connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS technical_evaluations(
              reviewer_id TEXT NOT NULL REFERENCES sessions(reviewer_id) ON DELETE CASCADE,
              clip_id TEXT NOT NULL, analysis_version TEXT NOT NULL,
              questionnaire_version TEXT NOT NULL, answers_json TEXT NOT NULL,
              measurement_json TEXT, comment TEXT NOT NULL,
              created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
              PRIMARY KEY(reviewer_id,clip_id,analysis_version,questionnaire_version))''')

    def save(self, rid, data):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.store.connect()) as conn, conn:
            conn.execute('''INSERT INTO technical_evaluations VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(reviewer_id,clip_id,analysis_version,questionnaire_version)
              DO UPDATE SET answers_json=excluded.answers_json, measurement_json=excluded.measurement_json,
                comment=excluded.comment,updated_utc=excluded.updated_utc''',
                (rid, data['clip_id'], data['analysis_version'], data['questionnaire_version'],
                 json.dumps(data['answers'], allow_nan=False),
                 json.dumps(data['stroke_measurement'], allow_nan=False) if data['stroke_measurement'] is not None else None,
                 data['comment'], now, now))

    @staticmethod
    def _decode(row):
        result = dict(row)
        result['answers'] = json.loads(result.pop('answers_json'))
        measurement = result.pop('measurement_json')
        result['stroke_measurement'] = json.loads(measurement) if measurement is not None else None
        result['assessment_type'] = 'human_perceived_assessment'
        return result

    def responses(self, rid, clip_id):
        with closing(self.store.connect()) as conn:
            return [self._decode(row) for row in conn.execute('''SELECT * FROM technical_evaluations
              WHERE reviewer_id=? AND clip_id=? ORDER BY updated_utc''', (rid, clip_id))]

    def rows(self):
        with closing(self.store.connect()) as conn:
            return [self._decode(row) for row in conn.execute('''SELECT e.*,s.role,s.experience
              FROM technical_evaluations e JOIN sessions s USING(reviewer_id) ORDER BY e.updated_utc''')]

    def summary(self):
        rows = self.rows()
        counts = Counter(answer['verdict'] for row in rows for answer in row['answers'].values())
        return {'assessment_count': len(rows), 'reviewer_count': len({row['reviewer_id'] for row in rows}),
                'verdict_counts': {key: counts[key] for key in VERDICTS},
                'manual_measurement_count': sum(row['stroke_measurement'] is not None for row in rows),
                'method': METHOD}

    def export_csv(self):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        for row in self.rows():
            measurement = row['stroke_measurement'] or {}
            base = {key: row[key] for key in ('reviewer_id', 'role', 'experience', 'clip_id', 'analysis_version',
                    'questionnaire_version', 'assessment_type', 'comment', 'created_utc', 'updated_utc')}
            base.update(manual_catch_count=measurement.get('catch_count'),
                        manual_first_catch_seconds=measurement.get('first_catch_seconds'),
                        manual_last_catch_seconds=measurement.get('last_catch_seconds'),
                        manual_rate_spm=measurement.get('rate_spm'),
                        manual_rower_reference=measurement.get('rower_reference'),
                        measurement_method=measurement.get('method'))
            for key, answer in row['answers'].items():
                item = dict(base, criterion_id=key, verdict=answer['verdict'],
                            timestamp_seconds=answer['timestamp_seconds'], criterion_comment=answer['comment'])
                writer.writerow({key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value)
                                 for key, value in item.items()})
        return out.getvalue().encode('utf-8-sig')
