"""Versioned report-level quality judgments; never fabricated model accuracy."""
from contextlib import closing
from datetime import datetime, timezone
import csv
import io

VERSION = 'quality-v1'
QUESTIONS = {
 'clarity': ('Clarity', 'How clear and easy to understand is this report?'),
 'specificity': ('Specificity', 'How specific is the feedback to this crew, rather than generic rowing advice?'),
 'completeness': ('Completeness', 'How well does the report cover the rowers and movements visible in this clip?'),
 'evidence_support': ('Evidence support', 'How well do the annotations and examples support the report\'s claims?'),
 'actionability': ('Actionability', 'How useful is this report for deciding what to review or work on next?'),
}
FIELDS = ['reviewer_id','role','experience','clip_id','analysis_version','questionnaire_version',
          'question_id','score','reason','comment','created_utc','updated_utc']


def public_questions():
    return [{'id':k,'title':v[0],'question':v[1]} for k,v in QUESTIONS.items()]


def validate_quality(data, clip):
    required={'clip_id','analysis_version','questionnaire_version','answers','comment'}
    if not isinstance(data,dict) or set(data)!=required:
        raise ValueError('invalid_quality_fields')
    if data['clip_id']!=clip['id'] or data['analysis_version']!=clip['analysis']['version']:
        raise ValueError('analysis_changed_reload')
    if data['questionnaire_version']!=VERSION:
        raise ValueError('quality_version_changed_reload')
    answers=data['answers']
    if not isinstance(answers,dict) or set(answers)!=set(QUESTIONS):
        raise ValueError('all_five_quality_answers_required')
    if not isinstance(data['comment'],str) or len(data['comment'])>2000 or '\x00' in data['comment']:
        raise ValueError('comment_too_long_or_invalid')
    rows=[]
    for key,value in answers.items():
        if type(value) is int and 1<=value<=5:score,reason=value,'rated'
        elif type(value) is str and value in ('cannot_judge','not_applicable'):
            score,reason=None,value
        else:raise ValueError('quality_rating_must_be_1_to_5_or_skip')
        rows.append({'clip_id':data['clip_id'],'analysis_version':data['analysis_version'],
            'questionnaire_version':VERSION,'question_id':key,'score':score,
            'reason':reason,'comment':data['comment'].strip()})
    return rows


class QualityStore:
    """Additive migration in the existing consent-owned SQLite database."""
    def __init__(self, review_store):
        self.store=review_store
        with closing(self.store.connect()) as c,c:
            c.execute('''CREATE TABLE IF NOT EXISTS quality_responses(
              reviewer_id TEXT NOT NULL REFERENCES sessions(reviewer_id) ON DELETE CASCADE,
              clip_id TEXT NOT NULL, analysis_version TEXT NOT NULL,
              questionnaire_version TEXT NOT NULL, question_id TEXT NOT NULL,
              score INTEGER CHECK(score IS NULL OR score BETWEEN 1 AND 5),
              reason TEXT NOT NULL CHECK(reason IN ('rated','cannot_judge','not_applicable')),
              comment TEXT NOT NULL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
              PRIMARY KEY(reviewer_id,clip_id,analysis_version,questionnaire_version,question_id),
              CHECK((reason='rated' AND score IS NOT NULL) OR (reason!='rated' AND score IS NULL)))''')
    def save(self,rid,rows):
        now=datetime.now(timezone.utc).isoformat()
        with closing(self.store.connect()) as c,c:
            for r in rows:
                c.execute('''INSERT INTO quality_responses VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(reviewer_id,clip_id,analysis_version,questionnaire_version,question_id)
                DO UPDATE SET score=excluded.score,reason=excluded.reason,
                  comment=excluded.comment,updated_utc=excluded.updated_utc''',
                  (rid,r['clip_id'],r['analysis_version'],r['questionnaire_version'],r['question_id'],
                   r['score'],r['reason'],r['comment'],now,now))
    def responses(self,rid,clip_id):
        with closing(self.store.connect()) as c:
            return [dict(r) for r in c.execute('SELECT * FROM quality_responses WHERE reviewer_id=? AND clip_id=? ORDER BY question_id',(rid,clip_id))]
    def rows(self):
        with closing(self.store.connect()) as c:
            return [dict(r) for r in c.execute('''SELECT q.*,s.role,s.experience FROM quality_responses q
              JOIN sessions s USING(reviewer_id) ORDER BY q.updated_utc,q.question_id''')]
    def export_csv(self):
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader()
        for row in self.rows():
            writer.writerow({k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()})
        return out.getvalue().encode('utf-8-sig')
