"""Hosted one-click demo contract: synthetic worker tests, never field model-accuracy claims."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

import httpx
from strokesense.web_demo_hosted import create_app

ORIGIN = "https://demo.example.test"
OWNER = "owner-" + "A" * 48
VALID_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"A" * 128

class HostedOneClickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture = (
            "from pathlib import Path;import sys,time;"
            "p=Path(sys.argv[1])/'synthetic';p.mkdir(parents=True,exist_ok=True);"
            "print('[1/4] Running pose estimation',flush=True);"
            "(p/'report.html').write_text('<h1>TEST FIXTURE ONLY</h1>');"
            "(p/'metrics.json').write_text('{}');"
            "(p/'crew_annotated.mp4').write_bytes(b'FAKE VIDEO')"
        )
        self.app = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER,
                              max_upload_bytes=1024,
                              command_factory=lambda: [sys.executable,"-c",fixture,str(self.root/"demo"/"outputs")])
        self.transport = httpx.ASGITransport(app=self.app)
    def tearDown(self):
        self.tmp.cleanup()

    async def req(self,method,path,*,origin=None,owner=False,csrf=False,body=None,headers=None):
        hdr=dict(headers or {})
        if origin is not None:hdr["Origin"]=origin
        if owner:hdr["Authorization"]="Bearer "+OWNER
        if csrf:hdr["X-Demo-CSRF"]=self.app.state.demo_csrf
        async with httpx.AsyncClient(transport=self.transport, base_url=ORIGIN) as c:
            return await c.request(method,path,content=body,headers=hdr)

    async def prepared(self):
        return await self.req("POST","/api/owner/demo-video",origin=ORIGIN,owner=True,
                              body=VALID_MP4,headers={"Content-Type":"video/mp4"})

    async def test_empty_site_has_no_fake_success(self):
        page=await self.req("GET","/demo")
        self.assertEqual(page.status_code,200)
        self.assertIn("not loaded",page.text.lower())
        self.assertEqual((await self.req("GET","/api/demo/status")).status_code,409)
        self.assertEqual((await self.req("GET","/demo/video")).status_code,404)
        self.assertFalse((self.root/"study").exists())

    async def test_owner_upload_requires_auth_and_origin(self):
        for kw in ({},{"owner":True},{"origin":"https://evil.example","owner":True}):
            response=await self.req("POST","/api/owner/demo-video",body=VALID_MP4,
                          headers={"Content-Type":"video/mp4"},**kw)
            self.assertEqual(response.status_code,403)
        self.assertFalse((self.root/"demo"/"prepared.mp4").exists())
        uploaded=await self.prepared()
        self.assertEqual(uploaded.status_code,201,uploaded.text)
        self.assertEqual(uploaded.json()["size_bytes"],len(VALID_MP4))
        self.assertTrue((self.root/"demo"/"prepared.mp4").exists())
        self.assertEqual((await self.prepared()).status_code,409)

    async def test_bad_video_and_size_fail_without_storage(self):
        invalid=await self.req("POST","/api/owner/demo-video",origin=ORIGIN,owner=True,
                    body=b"not an mp4",headers={"Content-Type":"video/mp4"})
        self.assertEqual(invalid.status_code,422)
        mime=await self.req("POST","/api/owner/demo-video",origin=ORIGIN,owner=True,
                    body=VALID_MP4,headers={"Content-Type":"application/zip"})
        self.assertEqual(mime.status_code,415)
        too_big=await self.req("POST","/api/owner/demo-video",origin=ORIGIN,owner=True,
                    body=VALID_MP4 * 10,headers={"Content-Type":"video/mp4"})
        self.assertEqual(too_big.status_code,413)
        self.assertFalse((self.root/"demo"/"prepared.mp4").exists())

    async def test_ready_page_and_seekable_video(self):
        self.assertEqual((await self.prepared()).status_code,201)
        page=await self.req("GET","/demo")
        self.assertIn("Analyze now",page.text)
        self.assertIn("Video Project 19",page.text)
        self.assertEqual((await self.req("GET","/api/demo/status")).json()["state"],"ready")
        video=await self.req("GET","/demo/video",headers={"Range":"bytes=0-9"})
        self.assertEqual(video.status_code,206)
        self.assertEqual(video.content,VALID_MP4[:10])
        self.assertEqual(video.headers.get("Content-Range"),"bytes 0-9/"+str(len(VALID_MP4)))
        self.assertEqual((await self.req("HEAD","/demo/video",headers={"Range":"bytes=0-3"})).status_code,206)
        self.assertEqual((await self.req("GET","/demo/video",headers={"Range":"bytes=4-1"})).status_code,416)
        self.assertEqual((await self.req("GET","/demo/video",headers={"Range":"bytes=1-2,3-4"})).status_code,416)

    async def test_start_requires_origin_csrf_and_json(self):
        await self.prepared()
        base={"body":b"{}","headers":{"Content-Type":"application/json"}}
        self.assertEqual((await self.req("POST","/api/demo/analyze",origin=ORIGIN,**base)).status_code,403)
        self.assertEqual((await self.req("POST","/api/demo/analyze",origin="https://evil.example",csrf=True,**base)).status_code,403)
        self.assertEqual((await self.req("POST","/api/demo/analyze",origin=ORIGIN,csrf=True,body=b"[]",headers=base["headers"])).status_code,400)
        self.assertEqual((await self.req("GET","/api/demo/status")).json()["state"],"ready")

    async def test_click_runs_worker_and_returns_artifacts(self):
        await self.prepared()
        result=await self.req("POST","/api/demo/analyze",origin=ORIGIN,csrf=True,
                              body=b"{}",headers={"Content-Type":"application/json"})
        self.assertEqual(result.status_code,202,result.text)
        for _ in range(140):
            snapshot=(await self.req("GET","/api/demo/status")).json()
            if snapshot["state"] in ("finished","failed"):break
            await asyncio.sleep(.025)
        self.assertEqual(snapshot["state"],"finished",snapshot)
        self.assertTrue(snapshot["has_report"])
        self.assertTrue(snapshot["has_overlay"])
        doc=await self.req("GET","/demo/report")
        self.assertEqual(doc.status_code,200)
        self.assertIn("TEST FIXTURE ONLY",doc.text)
        self.assertIn("sandbox",doc.headers.get("Content-Security-Policy",""))
        self.assertEqual((await self.req("GET","/demo/annotated")).content,b"FAKE VIDEO")
        self.assertEqual((await self.req("POST","/api/demo/analyze",origin=ORIGIN,csrf=True,
                     body=b"{}",headers={"Content-Type":"application/json"})).status_code,409)

    async def test_no_study_or_arbitrary_file_access(self):
        await self.prepared()
        self.assertFalse((self.root/"study").exists())
        self.assertEqual((await self.req("GET","/demo/../../etc/passwd")).status_code,404)
        outside=self.root/"private.txt";outside.write_text("secret")
        self.assertEqual((await self.req("GET","/demo/private.txt")).status_code,404)
        self.assertNotIn("secret",(await self.req("GET","/demo")).text)

    async def test_host_rejects_forgery(self):
        await self.prepared()
        bad=await self.req("GET","/api/demo/status",headers={"Host":"evil.example"})
        self.assertEqual(bad.status_code,403)

if __name__=="__main__":
    unittest.main()
