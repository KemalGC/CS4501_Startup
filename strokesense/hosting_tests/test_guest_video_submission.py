"""Guest review contract. Synthetic ratings/media, not real participants."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from starlette.testclient import TestClient
from test_hosted import HostedTests, ORIGIN, OWNER, package
from test_tester_links import ten_package


class GuestVideoSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = HostedTests()
        self.fixture.expected_clips = 7
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c = self.fixture.client
        self.assertEqual(self.fixture.upload(ten_package(count=7)).status_code, 201)
        self.csrf = self.c.get('/api/bootstrap').json()['csrf']
        self.headers = {'Origin':ORIGIN,'X-CSRF-Token':self.csrf}
    def enroll(self, name='Rowing Tester A'):
        r=self.c.post('/api/session',json={'display_name':name,'role':'rower','experience':'3to5','consent':True},headers=self.headers)
        self.assertEqual(r.status_code,201,r.text)
        return r.json()
    def review(self, clip='clip-1'):
        return {'clip_id':clip,'analysis_version':'r1','aspect_id':'rate','usefulness':4,
                'accuracy':4,'accuracy_reason':'rated','timestamp_seconds':1.2,'comment':'Checked video'}
    def test_public_library_requires_no_access_code_but_media_requires_name_and_consent(self):
        self.assertEqual(self.c.get('/library').status_code,200)
        self.assertEqual(self.c.get('/api/bootstrap').status_code,200)
        self.assertIsNone(self.c.get('/api/bootstrap').json()['session'])
        self.assertEqual(self.c.get('/asset/clip-1/video').status_code,401)
        self.assertEqual(self.c.get('/api/owner/export.csv').status_code,403)
        r=self.enroll()
        self.assertEqual(r['display_name'],'Rowing Tester A')
        self.assertEqual(self.c.get('/asset/clip-1/report').status_code,200)
        self.assertEqual(self.c.get('/api/owner/export.csv').status_code,403)
    def test_name_is_required_and_not_executable(self):
        base={'role':'rower','experience':'3to5','consent':True}
        for name in (None,'','   ','\n', 'A'*81,'Jane\nDoe', 'X\x00Y'):
            data=dict(base)
            if name is not None:data['display_name']=name
            with self.subTest(name=name):self.assertEqual(self.c.post('/api/session',json=data,headers=self.headers).status_code,422)
        self.enroll('  =SUM(1,2) Tester  ')
        self.c.post('/api/reviews',json=self.review(),headers=self.headers)
        owner=self.c.get('/api/owner/export.csv',headers={'Authorization':'Bearer '+OWNER})
        self.assertEqual(owner.status_code,200)
        self.assertIn(b"'=SUM(1,2) Tester",owner.content)
    def test_one_video_can_be_submitted_without_others_and_resubmitted(self):
        self.enroll()
        empty=self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'r1'},headers=self.headers)
        self.assertEqual(empty.status_code,422)
        self.assertEqual(self.c.post('/api/reviews',json=self.review(),headers=self.headers).status_code,200)
        sent=self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'r1'},headers=self.headers)
        self.assertEqual(sent.status_code,200,sent.text)
        self.assertEqual(sent.json()['saved']['aspect_count'],1)
        self.assertEqual(sent.json()['saved']['quality_count'],0)
        self.assertEqual(sent.json()['saved']['technical_count'],0)
        self.assertEqual([x['clip_id'] for x in self.c.get('/api/submissions').json()['submissions']],['clip-1'])
        self.assertEqual(self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'r1'},headers=self.headers).status_code,200)
        self.assertEqual(self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'older'},headers=self.headers).status_code,422)
        self.assertEqual(self.c.post('/api/submit-video',json={'clip_id':'clip-2','analysis_version':'r1'},headers=self.headers).status_code,422)
        self.assertEqual(self.c.get('/api/owner/submissions.json',headers={'Authorization':'Bearer '+OWNER}).json()['submissions'][0]['display_name'],'Rowing Tester A')
    def test_separate_named_sessions_and_partial_submission_survive_restart(self):
        a=self.enroll('Jane Tester')
        self.c.post('/api/reviews',json=self.review(),headers=self.headers)
        self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'r1'},headers=self.headers)
        cookies=list(self.c.cookies.jar)
        self.fixture.close_client()
        self.fixture.client=self.fixture.new_client();self.c=self.fixture.client
        for cookie in cookies:self.c.cookies.jar.set_cookie(cookie)
        self.assertEqual(self.c.get('/api/submissions').json()['submissions'][0]['clip_id'],'clip-1')
        csrf=self.c.get('/api/bootstrap').json()['csrf']
        headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}
        self.assertEqual(self.c.post('/api/withdraw',json={},headers=headers).status_code,200)
        self.assertEqual(self.c.get('/api/owner/submissions.json',headers={'Authorization':'Bearer '+OWNER}).json()['submissions'],[])
        self.assertEqual(self.c.get('/api/owner/export.json',headers={'Authorization':'Bearer '+OWNER}).json()['responses'],[])
    def test_one_video_quality_only_and_second_video_are_independent(self):
        self.enroll()
        self.assertEqual(self.c.post('/api/quality',json={'clip_id':'clip-2','analysis_version':'r1',
           'questionnaire_version':'quality-v1','answers':{k:3 for k in ('clarity','specificity','completeness','evidence_support','actionability')},'comment':'ok'},headers=self.headers).status_code,200)
        self.assertEqual(self.c.post('/api/submit-video',json={'clip_id':'clip-2','analysis_version':'r1'},headers=self.headers).json()['saved']['quality_count'],5)
        self.assertEqual(self.c.post('/api/reviews',json=self.review(),headers=self.headers).status_code,200)
        self.assertEqual(self.c.post('/api/submit-video',json={'clip_id':'clip-1','analysis_version':'r1'},headers=self.headers).status_code,200)
        self.assertEqual({x['clip_id'] for x in self.c.get('/api/submissions').json()['submissions']},{'clip-1','clip-2'})
        self.assertEqual(self.c.get('/api/owner/submissions.csv',headers={'Authorization':'Bearer '+OWNER}).status_code,200)
    def test_technical_only_can_submit_one_video(self):
        from strokesense.feedback_evaluation import QUESTIONS, VERSION
        self.enroll('Morgan Athlete')
        payload={'clip_id':'clip-3','analysis_version':'r1','questionnaire_version':VERSION,
                 'answers':{key:{'verdict':'cannot_judge','timestamp_seconds':None,'comment':''}
                            for key in QUESTIONS}, 'stroke_measurement':None,'comment':''}
        self.assertEqual(self.c.post('/api/evaluation',json=payload,headers=self.headers).status_code,200)
        submitted=self.c.post('/api/submit-video',json={'clip_id':'clip-3','analysis_version':'r1'},headers=self.headers)
        self.assertEqual(submitted.status_code,200)
        self.assertEqual(submitted.json()['saved'],{'aspect_count':0,'quality_count':0,'technical_count':1})

    def test_legacy_sessions_migrate_without_erasing_old_responses(self):
        import sqlite3
        from strokesense.feedback import ReviewStore
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'legacy.db'
            with sqlite3.connect(f) as con:
                con.executescript("""CREATE TABLE meta(version INTEGER NOT NULL); INSERT INTO meta VALUES(1);
                CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,reviewer_id TEXT UNIQUE NOT NULL,
                  role TEXT NOT NULL,experience TEXT NOT NULL,consent_utc TEXT NOT NULL);
                CREATE TABLE responses(reviewer_id TEXT NOT NULL,clip_id TEXT NOT NULL,
                  analysis_version TEXT NOT NULL,aspect_id TEXT NOT NULL,usefulness INTEGER,
                  accuracy INTEGER,accuracy_reason TEXT NOT NULL,comment TEXT NOT NULL,
                  timestamp_seconds REAL,created_utc TEXT NOT NULL,updated_utc TEXT NOT NULL,
                  PRIMARY KEY(reviewer_id,clip_id,analysis_version,aspect_id));""")
                con.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',('oldhash','oldperson','rower','3to5','oldtime'))
                con.execute('INSERT INTO responses VALUES(?,?,?,?,?,?,?,?,?,?,?)',('oldperson','clip-one','r1','rate',3,4,'rated','legacy',1.,'oldtime','oldtime'))
            store=ReviewStore(f)
            self.assertEqual(store.rows()[0]['comment'],'legacy')
            self.assertEqual(store.rows()[0]['display_name'],'')
            token=store.enroll('rower','skip',True,'A New Reviewer')
            self.assertEqual(store.session(token)['display_name'],'A New Reviewer')
            self.assertEqual(len(store.rows()),1)

    def test_cross_origin_missing_csrf_and_unenrolled_submit_fail(self):
        payload={'clip_id':'clip-1','analysis_version':'r1'}
        self.assertEqual(self.c.post('/api/submit-video',json=payload,headers=self.headers).status_code,401)
        self.enroll()
        self.assertEqual(self.c.post('/api/submit-video',json=payload,headers={'Origin':'https://evil.example.com','X-CSRF-Token':self.csrf}).status_code,403)
        self.assertEqual(self.c.post('/api/submit-video',json=payload,headers={'Origin':ORIGIN}).status_code,403)
        self.assertEqual(self.c.get('/api/owner/submissions.csv').status_code,403)

if __name__=='__main__':unittest.main()
