"""Real loopback requests; injected detector proposals, never live inference."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense.web import create_server
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip,revoke_clip

class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.review'), 'multi-frame review routes are missing')
        from strokesense.review import add_review
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        video=root/'synthetic.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(100,100))
        self.assertTrue(writer.isOpened())
        for _ in range(45):writer.write(np.zeros((100,100,3),np.uint8))
        writer.release();self.db=root/'registry.db'
        clip,_=register_clip(video,db=self.db,permission='granted',provenance='Synthetic test')
        self.cid=clip['clip_id'];self.seen=[]
        def analyze(path,*,out_dir,selection=None):
            self.seen.append(selection);report=out_dir/'report.html';report.write_text('Synthetic')
            return {'report':report}
        self.jobs=JobQueue(registry_db=self.db,job_db=root/'jobs.db',results_root=root/'results',analyze_fn=analyze)
        self.addCleanup(self.jobs.close)
        def scan(path):
            candidates=[{'id':i+1,'seed':[(12+i*10)/100,.35],'box':[(9+i*10)/100,.27,(15+i*10)/100,.43]} for i in range(8)]
            return {'state':'ready','frames':[{'seconds':1.,'image':'data:image/jpeg;base64,AA==','candidates':candidates,'boats':[]}], 'selected':[]}
        self.server=add_review(create_server(self.jobs,registry_db=self.db,port=0),self.jobs,self.db,scan_fn=scan)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.addCleanup(self.stop);self.origin=f'http://127.0.0.1:{self.server.server_address[1]}'
    def stop(self):
        self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,fields=None,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=5)
        body=urlencode(fields) if fields is not None else None
        headers={'Origin':origin or self.origin}
        if body is not None: headers['Content-Type']='application/x-www-form-urlencoded'
        c.request(method,path,body,headers);r=c.getresponse();data=r.read();h=dict(r.getheaders());c.close()
        return r.status,h,data
    def ready(self):
        status,_,body=self.request('GET','/review?'+urlencode({'clip':self.cid}))
        self.assertEqual(status,200);self.assertIn(b'Review later frames',body)
        for _ in range(50):
            status,_,body=self.request('GET','/review/status?'+urlencode({'clip':self.cid}))
            data=json.loads(body)
            if data['state']!='scanning': return data
            time.sleep(.01)
        self.fail('bounded synthetic scan did not finish')
    def form(self,data):
        return {'csrf':self.server.csrf_token,'clip':self.cid,'review':data['review'],
                'frame':'0','people':'0,1,2,3,4,5,6,7','same_boat':'yes'}
    def test_selection_does_not_start_work_until_explicit_confirmation(self):
        data=self.ready();self.assertEqual(self.jobs.list_recent(),[])
        status,h,_=self.request('POST','/review/confirm',self.form(data));self.assertEqual(status,303)
        self.jobs.wait(h['Location'].rsplit('/',1)[-1],timeout=5)
        self.assertEqual(len(self.seen),1);self.assertEqual(self.seen[0]['version'],2)
        self.assertEqual(self.seen[0]['reference_seconds'],1)
    def test_invalid_and_duplicate_selection_never_enqueue(self):
        data=self.ready();good=self.form(data)
        for key,value in [('people','0,1,2'),('people','0,1,2,3,4,5,6,6'),('frame','9'),('same_boat','no'),('review','0'*32)]:
            with self.subTest(key=key,value=value):
                status,_,_=self.request('POST','/review/confirm',dict(good,**{key:value}));self.assertGreaterEqual(status,400)
        self.assertEqual(self.jobs.list_recent(),[])
    def test_csrf_origin_and_revocation_preserved(self):
        data=self.ready();f=self.form(data)
        self.assertEqual(self.request('POST','/review/confirm',dict(f,csrf='bad'))[0],403)
        self.assertEqual(self.request('POST','/review/confirm',f,origin='http://foreign.example')[0],403)
        revoke_clip(self.cid,self.db)
        self.assertEqual(self.request('GET','/review/status?'+urlencode({'clip':self.cid}))[0],403)
        self.assertEqual(self.request('POST','/review/confirm',f)[0],403)
        self.assertEqual(self.jobs.list_recent(),[])

if __name__=='__main__':unittest.main()
