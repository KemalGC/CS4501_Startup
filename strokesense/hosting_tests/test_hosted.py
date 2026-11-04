"""Real HTTP review backend through hosted ASGI gateway; synthetic study only."""
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starlette.testclient import TestClient
from strokesense.feedback import ASPECTS

ORIGIN='https://review.example.com'
OWNER='owner-test-secret-'+'x'*32
INVITE='review-test-code-'+'y'*24

def package(extra=None, bad_path=None):
    clip={'id':'clip-one','title':'Synthetic clip','duration':10,'video':bad_path or 'media/test.mp4',
        'report':'reports/test.html','poster':'media/poster.jpg','annotated':'media/overlay.mp4',
        'analysis':{'version':'r1','status':'provisional',
        'aspects':{k:{'status':'available','summary':'Fixture'} for k in ASPECTS}}}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('Bundle/study/catalog.json',json.dumps({'schema_version':1,'clips':[clip]}))
        z.writestr('Bundle/study/media/test.mp4',b'0123456789')
        z.writestr('Bundle/study/media/overlay.mp4',b'0123456789')
        z.writestr('Bundle/study/media/poster.jpg',b'synthetic-poster')
        z.writestr('Bundle/study/reports/test.html','<h1>Fixture</h1><script>alert(1)</script>')
        if extra:z.writestr(*extra)
    return out.getvalue()

class HostedTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.feedback_hosted'), 'public hosting gateway missing')
        from strokesense.feedback_hosted import create_app
        self.create=create_app
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.client=self.new_client();self.addCleanup(self.close_client)
    def close_client(self):
        if self.client is not None:
            self.client.__exit__(None,None,None);self.client=None
    def new_client(self):
        client=TestClient(self.create(data_dir=self.root,origin=ORIGIN,owner_key=OWNER,review_code=INVITE,
            expected_clips=getattr(self, 'expected_clips', 1)),base_url=ORIGIN)
        client.__enter__();return client
    def post(self,path,data,**changes):
        headers={'Origin':ORIGIN,'X-CSRF-Token':self.client.get('/api/hosting').json()['csrf']}
        headers.update(changes)
        return self.client.post(path,json=data,headers=headers)
    def upload(self,blob=None):
        return self.client.post('/api/setup',content=blob or package(),headers={
          'Origin':ORIGIN,'Authorization':'Bearer '+OWNER,'Content-Type':'application/zip',
          'X-CSRF-Token':self.client.get('/api/hosting').json()['csrf']})
    def unlock(self):
        self.assertEqual(self.client.get('/library').status_code,200)
    def enroll(self):
        self.upload();self.unlock()
        bootstrap=self.client.get('/api/bootstrap').json();self.csrf=bootstrap['csrf']
        r=self.client.post('/api/session',json={'consent':True,'role':'rower','experience':'3to5','display_name':'Synthetic Rowing Tester'},headers={'Origin':ORIGIN,'X-CSRF-Token':self.csrf})
        self.assertEqual(r.status_code,201);self.assertIn('Secure',r.headers['set-cookie'])
    def review(self):
        return dict(clip_id='clip-one',analysis_version='r1',aspect_id='rate',usefulness=4,
          accuracy=3,accuracy_reason='rated',comment='=SUM(1,2)',timestamp_seconds=2.0)
    def test_missing_study_is_explicit_and_health_ready_is_false(self):
        self.assertEqual(self.client.get('/healthz').json()['study_ready'],False)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,503)
        self.assertEqual(self.client.get('/library').status_code,503)
        self.assertEqual(self.upload().status_code,201)
        self.assertTrue(self.client.get('/healthz').json()['study_ready'])
    def test_unsafe_configuration_fails_instead_of_trusting_every_host(self):
        for origin in ('http://review.example.com','https://review.example.com/extra','https://user@review.example.com','https://*.example.com'):
            with self.assertRaises(ValueError):self.create(data_dir=self.root,origin=origin,owner_key=OWNER,review_code=INVITE)
        with self.assertRaises(ValueError):self.create(data_dir=self.root,origin=ORIGIN,owner_key='short',review_code=INVITE)
    def test_foreign_hosts_origin_and_forwarded_headers_are_not_trusted(self):
        self.assertEqual(self.client.get('/',headers={'Host':'evil.example'}).status_code,403)
        self.assertEqual(self.post('/api/access',{'code':INVITE},Origin='https://evil.example').status_code,403)
        self.assertEqual(self.client.post('/api/access',json={'code':INVITE}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Host':'evil.example','X-Forwarded-Host':'review.example.com'}).status_code,403)
    def test_invite_owner_and_csrf_gates(self):
        self.assertEqual(self.post('/api/access',{'code':'wrong'}).status_code,410)
        self.assertEqual(self.post('/api/setup',{'anything':'x'},**{'X-CSRF-Token':'wrong'}).status_code,403)
        self.assertEqual(self.client.post('/api/setup',content=package(),headers={'Origin':ORIGIN}).status_code,403)
        self.upload();self.unlock()
        self.assertEqual(self.client.get('/asset/clip-one/video').status_code,401)
        self.assertEqual(self.client.get('/api/owner/export.json').status_code,403)
    def test_video_ranges_head_and_report_sandbox(self):
        self.enroll()
        r=self.client.get('/asset/clip-one/video',headers={'Range':'bytes=2-5'})
        self.assertEqual((r.status_code,r.content),(206,b'2345'))
        self.assertEqual(r.headers['content-range'],'bytes 2-5/10')
        self.assertEqual(self.client.head('/asset/clip-one/video').content,b'')
        self.assertIn("sandbox;",self.client.get('/asset/clip-one/report').headers['content-security-policy'])
        self.assertEqual(self.client.get('/study/.feedback/reviews.sqlite3').status_code,404)
    def test_reviews_and_five_quality_responses_survive_restart_and_withdraw(self):
        self.enroll();h={'Origin':ORIGIN,'X-CSRF-Token':self.csrf}
        self.assertEqual(self.client.post('/api/reviews',json=self.review(),headers=h).status_code,200)
        q={'clip_id':'clip-one','analysis_version':'r1','questionnaire_version':'quality-v1',
          'answers':{k:4 for k in ('clarity','specificity','completeness','evidence_support','actionability')},'comment':'Test'}
        self.assertEqual(self.client.post('/api/quality',json=q,headers=h).status_code,200)
        cookies=list(self.client.cookies.jar)
        self.close_client()  # Stop and close the first backend, not just reload a page.
        self.client=self.new_client();other=self.client
        try:
            for cookie in cookies:other.cookies.jar.set_cookie(cookie)
            self.assertEqual(len(other.get('/api/responses?clip=clip-one').json()['responses']),1)
            self.assertEqual(len(other.get('/api/quality?clip=clip-one').json()['responses']),5)
            csv=other.get('/api/owner/export.csv',headers={'Authorization':'Bearer '+OWNER})
            self.assertIn(b"'=SUM",csv.content)
            csrf=other.get('/api/bootstrap').json()['csrf']
            self.assertEqual(other.post('/api/withdraw',json={},headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code,200)
            rows=other.get('/api/owner/quality.json',headers={'Authorization':'Bearer '+OWNER}).json()['responses']
            self.assertEqual(rows,[])
        finally:self.close_client()
    def test_setup_rejects_overwrite_and_preserves_database(self):
        self.enroll();before=(self.root/'study/.feedback/reviews.sqlite3').read_bytes()
        self.assertEqual(self.upload().status_code,409)
        self.assertEqual(before,(self.root/'study/.feedback/reviews.sqlite3').read_bytes())
    def test_bad_archives_leave_no_active_study(self):
        for payload in (package(extra=('../escape','bad')),package(bad_path='../outside.mp4'),b'notzip'):
            with self.subTest():
                self.assertEqual(self.upload(payload).status_code,422)
                self.assertFalse((self.root/'study').exists())
        self.assertFalse((self.root/'escape').exists())
    def test_small_routes_are_bounded_and_unknown_methods_are_rejected(self):
        self.assertEqual(self.post('/api/access',{'code':'x'*20000}).status_code,410)
        self.assertEqual(self.client.delete('/api/owner/export.json').status_code,405)

if __name__=='__main__':unittest.main()
