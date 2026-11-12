"""Invitation and ten-report library contracts; no real participant data."""
import io
import json
from pathlib import Path
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import zipfile
import test_hosted as fixtures


def ten_package(video=b'0123456789', poster=b'fixture', count=10):
    clips=[];out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('Study/study/media/video.mp4',video)
        z.writestr('Study/study/media/overlay.mp4',video)
        z.writestr('Study/study/media/poster.jpg',poster)
        for i in range(1,count+1):
            name=f'reports/report-{i}.html'
            z.writestr('Study/study/'+name,f'<h1>Report for clip {i}</h1><p>Synthetic test evidence only.</p>')
            clips.append({'id':f'clip-{i}','title':f'Test recording {i}','duration':2,
                'video':'media/video.mp4','annotated':'media/overlay.mp4','poster':'media/poster.jpg','report':name,
                'analysis':{'version':'r1','status':'provisional','window':{'start':0.,'end':2.},
                  'aspects':{k:{'status':'available','summary':'Synthetic fixture'} for k in fixtures.ASPECTS}}})
        z.writestr('Study/study/catalog.json',json.dumps({'schema_version':1,'clips':clips}))
    return out.getvalue()


class TesterLinkTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.HostedTests();self.base.expected_clips=10;self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.c=self.base.client
    def provision(self):
        self.assertEqual(self.base.upload(ten_package()).status_code,201)
    def invitation(self):
        return self.c.get('/api/owner/invitation',headers={'Authorization':'Bearer '+fixtures.OWNER})
    def token(self):
        r=self.invitation();self.assertEqual(r.status_code,200)
        url=r.json()['url'];return parse_qs(urlsplit(url).fragment)['invite'][0]
    def redeem(self,token,**headers):
        return self.base.post('/api/redeem',{'token':token},**headers)
    def enroll(self):
        boot=self.c.get('/api/bootstrap').json()
        h={'Origin':fixtures.ORIGIN,'X-CSRF-Token':boot['csrf']}
        r=self.c.post('/api/session',json={'consent':True,'role':'rower','experience':'3to5'},headers=h)
        self.assertEqual(r.status_code,201);return h,r.json()['reviewer_id']
    def test_hosted_home_is_main_library_and_clip_query_is_preserved(self):
        r=self.c.get('/',follow_redirects=False)
        self.assertEqual(r.status_code,307);self.assertEqual(r.headers['location'],'/library')
        r=self.c.get('/?clip=clip-3',follow_redirects=False)
        self.assertEqual(r.headers['location'],'/library?clip=clip-3')
    def test_owner_and_join_pages_do_not_reveal_secrets(self):
        for path in ('/owner','/join'):
            r=self.c.get(path);self.assertEqual(r.status_code,200)
            self.assertNotIn(fixtures.OWNER,r.text);self.assertNotIn(fixtures.INVITE,r.text)
        self.assertIn('Copy tester link',self.c.get('/owner').text)
    def test_owner_gate_and_complete_study_gate_before_link_generation(self):
        self.assertEqual(self.c.get('/api/owner/invitation').status_code,403)
        self.assertEqual(self.invitation().status_code,409)
        self.provision();r=self.invitation();self.assertEqual(r.status_code,200)
        url=r.json()['url'];u=urlsplit(url)
        self.assertEqual(u.scheme,'https');self.assertEqual(u.netloc,'review.example.com')
        self.assertEqual(u.path,'/join');self.assertEqual(u.query,'')
        self.assertNotIn(fixtures.OWNER,url);self.assertNotIn(fixtures.INVITE,url)
        self.assertEqual(r.json()['readiness']['clip_count'],10)
    def test_missing_report_or_annotation_blocks_invitation(self):
        self.provision();p=self.base.root/'study/reports/report-10.html';p.unlink()
        r=self.invitation();self.assertEqual(r.status_code,409);self.assertNotIn('url',r.json())
        self.assertIn('clip-10',json.dumps(r.json()))
    def test_wrong_clip_count_does_not_look_ready(self):
        self.assertEqual(self.base.upload(ten_package(count=8)).status_code,201)
        r=self.invitation();self.assertEqual(r.status_code,409)
        self.assertEqual(r.json()['readiness']['expected_clips'],10)
    def test_redeemed_link_still_requires_consent_and_never_owner_rights(self):
        self.provision();r=self.redeem(self.token());self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['next'],'/library');self.assertIn('Secure',r.headers['set-cookie'])
        self.assertEqual(self.c.get('/asset/clip-1/report').status_code,401)
        self.enroll()
        for i in range(1,11):
            report=self.c.get(f'/asset/clip-{i}/report')
            self.assertEqual(report.status_code,200);self.assertIn(f'Report for clip {i}',report.text)
            self.assertIn('sandbox',report.headers['content-security-policy'])
        self.assertEqual(self.c.get('/api/owner/export.json').status_code,403)
    def test_tampered_expired_and_cross_origin_links_fail(self):
        self.provision();token=self.token()
        self.assertEqual(self.redeem(token+'x').status_code,403)
        self.assertEqual(self.redeem(token,Origin='https://evil.example').status_code,403)
        with patch('time.time',return_value=time.time()+8*86400):
            self.assertEqual(self.redeem(token).status_code,403)
        self.assertEqual(self.c.get('/join?invite='+token).status_code,400)
    def test_redeem_refuses_study_that_became_incomplete(self):
        self.provision();token=self.token();(self.base.root/'study/media/overlay.mp4').unlink()
        self.assertEqual(self.redeem(token).status_code,409)
    def test_five_reviewer_sessions_keep_separate_aspect_and_quality_answers(self):
        self.provision();token=self.token();ids=[]
        for i in range(1,6):
            self.c.cookies.clear();self.assertEqual(self.redeem(token).status_code,200)
            h,rid=self.enroll();ids.append(rid)
            self.assertEqual(self.c.get('/api/responses?clip=clip-1').json()['responses'],[])
            data=dict(self.base.review(),clip_id='clip-1',usefulness=i,timestamp_seconds=1.)
            self.assertEqual(self.c.post('/api/reviews',json=data,headers=h).status_code,200)
            q={'clip_id':'clip-1','analysis_version':'r1','questionnaire_version':'quality-v2',
               'answers':{k:i for k in ('clarity','specificity','completeness','actionability')},'comment':'Synthetic'}
            self.assertEqual(self.c.post('/api/quality',json=q,headers=h).status_code,200)
        self.assertEqual(len(set(ids)),5)
        r=self.c.get('/api/owner/quality.json',headers={'Authorization':'Bearer '+fixtures.OWNER})
        self.assertEqual(len(r.json()['responses']),20)
    def test_fragment_is_removed_before_network_calls_and_no_open_redirect(self):
        r=self.c.get('/sharing.js');self.assertEqual(r.status_code,200)
        self.assertLess(r.text.index('history.replaceState'),r.text.index("fetch('/api/hosting'"))
        self.assertNotIn('location.href=token',r.text)

if __name__=='__main__':unittest.main()
