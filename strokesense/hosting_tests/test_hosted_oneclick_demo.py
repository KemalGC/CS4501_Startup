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
from strokesense.oneclick_demo import summarize_crew_metrics, DemoState

ORIGIN = "https://demo.example.test"
OWNER = "owner-" + "A" * 48
VALID_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"A" * 128

class HostedOneClickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture = (
            "from pathlib import Path;import sys,time,json;"
            "p=Path(sys.argv[1])/'synthetic';p.mkdir(parents=True,exist_ok=True);"
            "print('[1/4] Running pose estimation',flush=True);"
            "(p/'report.html').write_text('<h1>TEST FIXTURE ONLY</h1>');"
            "(p/'metrics.json').write_text(json.dumps({'rowers':[ {'seat':str(i),'strokes':[{}]*2} for i in range(8)],'crew_cadence':{'rate_spm':30.1}}));"
            "(p/'crew_annotated.mp4').write_bytes(b'FAKE VIDEO')"
        )
        self.app = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER,
                              max_upload_bytes=1024,
                              legacy_demo_routes=True,
                              command_factory=lambda: [sys.executable,"-c",fixture,str(self.app.state.demo_data['demo'].root)])
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
        self.assertIn("media-src 'self'",video.headers["Content-Security-Policy"])
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
        self.assertEqual(snapshot["crew_summary"]["candidate_rowers"],8)
        self.assertEqual(snapshot["crew_summary"]["observed_cycles"],16)
        self.assertEqual(snapshot["crew_summary"]["shared_rate_spm"],30.1)
        self.assertTrue(snapshot["has_overlay"])
        doc=await self.req("GET","/demo/report")
        self.assertEqual(doc.status_code,200)
        self.assertIn("TEST FIXTURE ONLY",doc.text)
        self.assertIn("sandbox",doc.headers.get("Content-Security-Policy",""))
        annotated=await self.req("GET","/demo/annotated")
        self.assertEqual(annotated.content,b"FAKE VIDEO")
        self.assertEqual(annotated.headers["Content-Type"],"video/mp4")
        self.assertIn("media-src 'self'",annotated.headers["Content-Security-Policy"])
        for method in ("GET","HEAD"):
            ranged=await self.req(method,"/demo/annotated",headers={"Range":"bytes=0-3"})
            self.assertEqual(ranged.status_code,206)
            self.assertEqual(ranged.headers["Content-Range"],"bytes 0-3/10")
            self.assertIn("media-src 'self'",ranged.headers["Content-Security-Policy"])
        self.assertEqual((await self.req("POST","/api/demo/analyze",origin=ORIGIN,csrf=True,
                     body=b"{}",headers={"Content-Type":"application/json"})).status_code,202)
        for _ in range(140):
            rerun=(await self.req("GET","/api/demo/status")).json()
            if rerun["state"] in ("finished","failed"):break
            await asyncio.sleep(.025)
        self.assertEqual(rerun["state"],"finished",rerun)

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

class CrewMetricsContractTests(unittest.TestCase):
    def fixture(self, n=8, cycles=2, rate=30.):
        return {"rowers": [{"seat": f"R{i}","strokes": [{}]*cycles} for i in range(n)],
                "crew_cadence": {"rate_spm": rate}}

    def test_one_shared_rate_for_eight_tracks(self):
        summary = summarize_crew_metrics(self.fixture())
        self.assertEqual(summary['candidate_rowers'],8)
        self.assertEqual(summary['observed_cycles'],16)
        self.assertEqual(summary['shared_rate_spm'],30.)
        self.assertTrue(summary['full_eight_observed'])

    def test_partial_crew_is_explicit_not_falsely_eight(self):
        summary = summarize_crew_metrics(self.fixture(n=5,rate=None))
        self.assertEqual(summary['candidate_rowers'],5)
        self.assertIsNone(summary['shared_rate_spm'])
        self.assertFalse(summary['full_eight_observed'])

    def test_no_usable_stroke_cycles_cannot_claim_finished(self):
        with self.assertRaisesRegex(ValueError,'no_usable_strokes'):
            summarize_crew_metrics(self.fixture(cycles=0))

    def test_missing_or_malformed_metrics_rejected(self):
        for bad in ({}, {'rowers': []}, {'rowers':[{},{}]},
                    {'rowers':[{'seat':'R1','strokes':[{}]}, {'seat':'R1','strokes':[{}]}],
                     'crew_cadence':{'rate_spm':30}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                summarize_crew_metrics(bad)

    def test_nonfinite_rate_rejected(self):
        for rate in (float('nan'),float('inf'),-1,True,1000):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError,'invalid_crew_cadence'):
                summarize_crew_metrics(self.fixture(rate=rate))

    def test_real_command_uses_pose_cli_and_dominant_crew(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'prepared.mp4';source.write_bytes(VALID_MP4)
            demo=DemoState(source,Path(temp)/'results')
            command=demo._command()
            self.assertEqual(command[1:4],['-u','-m','strokesense.cli'])
            self.assertIn('--dominant-crew',command)
            self.assertIn('--fps',command)
            self.assertEqual(command[command.index('--fps')+1],'10')

    def test_status_does_not_expose_crew_metrics_before_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'prepared.mp4';source.write_bytes(VALID_MP4)
            demo=DemoState(source,Path(temp)/'results')
            self.assertIsNone(demo.snapshot()['crew_summary'])

if __name__=="__main__":
    unittest.main()
