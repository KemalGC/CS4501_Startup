"""Offline one-click UI tests. Fake analyzer never claims to be field model accuracy."""
from __future__ import annotations
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.oneclick_demo import create_server, _safe_media, _safe_result


class OneClickDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.video=self.root/'IMG_5092_eights_16s.mp4'
        self.video.write_bytes(b'00000000ftyp'+b'A'*200)
        out=self.root/'generated'
        fake='''from pathlib import Path\nimport sys,time\np=Path(sys.argv[1])/'example'\np.mkdir(parents=True,exist_ok=True)\nprint('[1/4] Running pose estimation',flush=True)\nprint('frame 30/80',flush=True)\n(p/'report.html').write_text('<h1>Fresh synthetic report</h1>')\n(p/'metrics.json').write_text('\\{\\"synthetic\\":true\\}')\n(p/'crew_annotated.mp4').write_bytes(b'FAKE_OUTPUT')\n'''
        # Avoid malformed escape sequences in test fixture JSON.
        fake=fake.replace("'\\{\\\"synthetic\\\":true\\}'", "'{}'")
        self.server=create_server(self.video,output_dir=out,port=0,command_factory=lambda:[sys.executable,'-c',fake,str(out)])
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close()
        self.tmp.cleanup()

    def call(self,path,*,method='GET',body=None,csrf=None,origin=None,extra=None):
        headers=extra or {}
        if body is not None:headers['Content-Type']='application/json'
        if csrf is not None:headers['X-CSRF-Token']=csrf
        if origin is not None:headers['Origin']=origin
        req=urllib.request.Request(self.base+path,data=body,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=10) as resp:
                return resp.status,resp.read(),dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read(),dict(exc.headers)

    def start(self):
        return self.call('/api/analyze',method='POST',body=b'{}',csrf=self.server.csrf,origin=self.base)

    def await_end(self):
        for _ in range(150):
            s=json.loads(self.call('/api/status')[1])
            if s['state'] in ('finished','failed'):return s
            time.sleep(.02)
        self.fail('worker did not complete')

    def test_prepared_video_has_no_analyzer_side_effect_before_click(self):
        status=json.loads(self.call('/api/status')[1]);self.assertEqual(status['state'],'ready')
        p=self.call('/')[1];self.assertIn(b'Analyze now',p);self.assertIn(b'16-second',p)
        self.assertEqual(self.call('/report')[0],404)

    def test_range_and_head_seek(self):
        s,body,h=self.call('/video',extra={'Range':'bytes=10-19'})
        self.assertEqual(s,206);self.assertEqual(body,self.video.read_bytes()[10:20])
        self.assertEqual(h['Content-Range'],'bytes 10-19/212')
        self.assertEqual(self.call('/video',method='HEAD',extra={'Range':'bytes=0-4'})[0],206)
        self.assertEqual(self.call('/video',extra={'Range':'bytes=999-1000'})[0],416)
        self.assertEqual(self.call('/video',extra={'Range':'bytes=0-0,2-2'})[0],416)

    def test_one_click_runs_fresh_subprocess_and_returns_real_file_paths(self):
        self.assertEqual(self.start()[0],202)
        a=self.await_end();self.assertEqual(a['state'],'finished',a)
        self.assertTrue(a['has_report']);self.assertTrue(a['has_overlay'])
        code,html,_=self.call('/report');self.assertEqual(code,200)
        self.assertIn(b'Fresh synthetic report',html)
        code,data,_=self.call('/annotated');self.assertEqual(code,200)
        self.assertEqual(data,b'FAKE_OUTPUT')
        self.assertEqual(self.start()[0],409)

    def test_missing_csrf_and_mismatched_origin_cannot_trigger(self):
        self.assertEqual(self.call('/api/analyze',method='POST',body=b'{}',origin=self.base)[0],403)
        self.assertEqual(self.call('/api/analyze',method='POST',body=b'{}',csrf=self.server.csrf,origin='https://evil.example')[0],403)
        self.assertEqual(json.loads(self.call('/api/status')[1])['state'],'ready')

    def test_bad_payload_does_not_launch(self):
        self.assertEqual(self.call('/api/analyze',method='POST',body=b'[]',csrf=self.server.csrf,origin=self.base)[0],400)
        self.assertEqual(self.call('/api/analyze',method='POST',body=b'{}x',csrf=self.server.csrf,origin=self.base)[0],400)
        self.assertEqual(json.loads(self.call('/api/status')[1])['state'],'ready')

    def test_forged_host_cannot_read_even_video(self):
        self.assertEqual(self.call('/video',extra={'Host':'not-local.example'})[0],403)

    def test_no_arbitrary_result_access_and_symlinks_are_rejected(self):
        outside=self.root/'elsewhere.html';outside.write_text('NO')
        self.assertFalse(_safe_result(self.root/'generated',outside))
        symlink=self.root/'generated'/'spoof.html'
        try:
            symlink.symlink_to(outside)
        except OSError:
            pass
        else:
            self.assertFalse(_safe_result(self.root/'generated',symlink))
        self.assertEqual(self.call('/private/elsewhere.html')[0],404)

    def test_missing_video_fails_closed(self):
        with self.assertRaises(FileNotFoundError):create_server(self.root/'no.mp4',port=0)
        dummy=self.root/'bad.txt';dummy.write_text('abc')
        with self.assertRaises(ValueError):create_server(dummy,port=0)


if __name__=='__main__':unittest.main()
