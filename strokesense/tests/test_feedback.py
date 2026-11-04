"""Rower review behavior; all submissions and media here are synthetic fixtures."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import http.client
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.feedback'), 'review website is missing')
        from strokesense import feedback
        self.f=feedback;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'test.mp4').write_bytes(b'0123456789')
        self.clip={'id':'clip-one','title':'Synthetic clip','group_id':'one','duration':10.,'video':'test.mp4','analysis':{'version':'revision1','status':'provisional','method':'Synthetic test','aspects':{k:{'status':'available','summary':'Synthetic claim'} for k in feedback.ASPECTS}}}
        (self.root/'catalog.json').write_text(json.dumps({'schema_version':1,'clips':[self.clip]}))
        self.server=feedback.create_server(self.root,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.port=self.server.server_address[1];self.origin=f'http://127.0.0.1:{self.port}';self.cookie=None
        status,h,b=self.request('GET','/api/bootstrap');self.assertEqual(status,200);self.csrf=json.loads(b)['csrf']
    def stop(self):
        self.server.shutdown();self.thread.join(2);self.server.server_close()
    def request(self,method,path,data=None,headers=None):
        hdr={'Origin':self.origin}
        if self.cookie:hdr['Cookie']=self.cookie
        if hasattr(self,'csrf'):hdr['X-CSRF-Token']=self.csrf
        if headers:hdr.update(headers)
        raw=None if data is None else json.dumps(data)
        if raw is not None:hdr['Content-Type']='application/json'
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5);c.request(method,path,raw,hdr)
        r=c.getresponse();b=r.read();h=dict(r.getheaders());status=r.status;c.close();return status,h,b
    def enroll(self):
        s,h,b=self.request('POST','/api/session',{'consent':True,'role':'rower','experience':'3to5','display_name':'Synthetic Tester'})
        self.assertEqual(s,201);self.cookie=h['Set-Cookie'].split(';')[0];return json.loads(b)
    def review(self,**changes):
        return dict({'clip_id':'clip-one','analysis_version':'revision1','aspect_id':'rate','usefulness':4,'accuracy':None,'accuracy_reason':'cannot_judge','comment':'Not enough visible entries.','timestamp_seconds':3.2},**changes)
    def test_requires_consent_and_session(self):
        self.assertEqual(self.request('POST','/api/reviews',self.review())[0],401)
        self.assertEqual(self.request('POST','/api/session',{'consent':False,'role':'rower','experience':'3to5','display_name':'Synthetic Tester'})[0],422)
    def test_save_resume_and_update_are_not_duplicate_participants(self):
        self.enroll();self.assertEqual(self.request('POST','/api/reviews',self.review())[0],200)
        self.assertEqual(self.request('POST','/api/reviews',self.review(usefulness=5))[0],200)
        s,_,b=self.request('GET','/api/responses?clip=clip-one');rows=json.loads(b)['responses']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['usefulness'],5)
        _,_,b=self.request('GET','/api/owner/summary',headers={'Authorization':'Bearer '+self.server.owner_key})
        d=json.loads(b);self.assertEqual(d['reviewer_count'],1);self.assertEqual(d['response_count'],1)
    def test_accuracy_unavailable_remains_distinct_from_low_score(self):
        self.enroll();self.request('POST','/api/reviews',self.review())
        _,_,b=self.request('GET','/api/owner/summary',headers={'Authorization':'Bearer '+self.server.owner_key})
        rate=next(x for x in json.loads(b)['aspects'] if x['aspect_id']=='rate')
        self.assertEqual(rate['accuracy_n'],0);self.assertIsNone(rate['accuracy_mean']);self.assertEqual(rate['cannot_judge_n'],1)
    def test_rejects_tampering_wrong_revision_invalid_numbers_and_long_comments(self):
        self.enroll()
        for patch in [{'aspect_id':'madeup'},{'clip_id':'missing'},{'analysis_version':'stale'},{'accuracy':True},{'timestamp_seconds':11},{'timestamp_seconds':float('nan')},{'usefulness':6},{'comment':'x'*2001}]:
            with self.subTest(patch=patch):self.assertGreaterEqual(self.request('POST','/api/reviews',self.review(**patch))[0],400)
    def test_cross_origin_and_wrong_csrf_rejected(self):
        self.enroll()
        self.assertEqual(self.request('POST','/api/reviews',self.review(),{'Origin':'https://foreign.example'})[0],403)
        self.assertEqual(self.request('POST','/api/reviews',self.review(),{'X-CSRF-Token':'bad'})[0],403)
    def test_owner_data_not_public_or_visible_to_other_reviewers(self):
        self.enroll();self.request('POST','/api/reviews',self.review())
        self.assertEqual(self.request('GET','/api/owner/export.json')[0],403)
        self.cookie=None;self.enroll();_,_,b=self.request('GET','/api/responses?clip=clip-one')
        self.assertEqual(json.loads(b)['responses'],[])
    def test_range_playback_head_and_path_traversal(self):
        self.enroll();s,h,b=self.request('GET','/asset/clip-one/video',headers={'Range':'bytes=2-5'})
        self.assertEqual((s,b),(206,b'2345'));self.assertEqual(h['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.request('GET','/asset/clip-one/video',headers={'Range':'bytes=20-'})[0],416)
        self.assertEqual(self.request('HEAD','/asset/clip-one/video')[0],200)
        self.assertGreaterEqual(self.request('GET','/asset/../catalog.json')[0],400)
    def test_exports_escape_csv_formulas_and_withdraw_removes_own_response(self):
        self.enroll();self.request('POST','/api/reviews',self.review(comment='=2+2'))
        _,_,b=self.request('GET','/api/owner/export.csv',headers={'Authorization':'Bearer '+self.server.owner_key})
        self.assertIn(b"'=2+2",b)
        self.assertEqual(self.request('POST','/api/withdraw',{})[0],200)
        _,_,b=self.request('GET','/api/owner/summary',headers={'Authorization':'Bearer '+self.server.owner_key})
        self.assertEqual(json.loads(b)['response_count'],0)
    def test_sandboxed_report_and_private_cache_headers(self):
        self.assertEqual(self.request('GET','/api/bootstrap')[1]['Cache-Control'],'no-store')
        _,_,body=self.request('GET','/')
        self.assertIn(b'StrokeSense',body);self.assertIn(b'feedback',body.lower())
    def test_manifest_rejects_media_outside_pack(self):
        bad=dict(self.clip,video='../secret.mp4');(self.root/'bad.json').write_text(json.dumps({'schema_version':1,'clips':[bad]}))
        with self.assertRaises(ValueError):self.f.load_catalog(self.root/'bad.json')

if __name__=='__main__':unittest.main()
