"""Completed-run JPEG routes must stay bounded and per-video isolated."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

import httpx

from strokesense.web_demo_hosted import create_app


ORIGIN = 'https://demo.example.test'
OWNER = 'owner-' + 'A' * 48
JPEG = b'\xff\xd8JPEG fixture\xff\xd9'


class HostedGalleryRoutes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        demo = self.root / 'demo'
        demo.mkdir()
        (demo / 'prepared.mp4').write_bytes(b'private test video')
        self.app = create_app(data_dir=self.root, origin=ORIGIN, owner_key=OWNER)
        prepared_root = demo / 'outputs'
        prepared_run = prepared_root / 'prepared-fixture'
        prepared_run.mkdir(parents=True)
        self.prepared = self._completed(prepared_run, prepared_root)
        self.app.state.demo_data['demo'] = self.prepared
        self.visitor_id = 'b' * 48
        visitor_root = demo / 'visitor-uploads' / self.visitor_id / 'outputs'
        visitor_run = visitor_root / 'visitor-fixture'
        visitor_run.mkdir(parents=True)
        self.visitor = self._completed(visitor_run, visitor_root)
        self.app.state.demo_data['uploads'][self.visitor_id] = {
            'name': 'Visitor video', 'created': time.time(), 'state': self.visitor,
            'queued': False, 'cancelled': False,
        }

    def tearDown(self):
        self.temp.cleanup()

    def _completed(self, run, output_root):
        report = run / 'report.html'
        report.write_text('<h1>Private report fixture</h1>', encoding='utf-8')
        (run / 'metrics.json').write_text(json.dumps({
            'crew_cadence': {'rate_spm': 31},
            'rowers': [
                {'seat': 'R1', 'track': 0, 'strokes': [{}, {}], 'summary': {
                    'n_strokes': 2, 'issues': [{'code': 'early_body',
                        'title': 'Opening the back too early', 'frac': .5}]}},
                {'seat': 'R2', 'track': 1, 'strokes': [], 'summary': {'n_strokes': 0}},
            ],
        }), encoding='utf-8')
        (run / 'fault_0_early_body.jpg').write_bytes(JPEG)
        return SimpleNamespace(
            snapshot=lambda: {'state': 'finished'}, report=report,
            output_root=output_root, run_id='f' * 32, last_end=None,
        )

    async def request(self, method, url):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url=ORIGIN) as client:
            return await client.request(method, url)

    async def test_prepared_and_visitor_images_are_readable_after_completion(self):
        prepared = await self.request('GET', '/demo/snapshots/fault_0_early_body.jpg')
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(prepared.content, JPEG)
        self.assertEqual(prepared.headers['content-type'], 'image/jpeg')
        self.assertEqual(prepared.headers['cache-control'], 'no-store')
        visitor_path = f'/demo/videos/{self.visitor_id}/snapshots/fault_0_early_body.jpg'
        visitor = await self.request('GET', visitor_path)
        self.assertEqual(visitor.status_code, 200)
        self.assertEqual(visitor.content, JPEG)
        head = await self.request('HEAD', visitor_path)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        dashboard = await self.request('GET', f'/api/demo/videos/{self.visitor_id}/dashboard')
        self.assertEqual(dashboard.status_code, 200)
        url = dashboard.json()['rowers'][0]['snapshots'][0]['url']
        self.assertEqual(url, visitor_path)

    async def test_access_is_not_allowed_while_processing(self):
        self.prepared.snapshot = lambda: {'state': 'running'}
        self.visitor.snapshot = lambda: {'state': 'running'}
        prepared = await self.request('GET', '/demo/snapshots/fault_0_early_body.jpg')
        visitor = await self.request('GET',
            f'/demo/videos/{self.visitor_id}/snapshots/fault_0_early_body.jpg')
        self.assertEqual(prepared.status_code, 404)
        self.assertEqual(visitor.status_code, 404)

    async def test_traversal_symlink_and_unexpected_names_are_rejected(self):
        run = self.prepared.report.parent
        outside = self.root / 'secret.jpg'
        outside.write_bytes(JPEG)
        (run / 'fault_0_early_body_before.jpg').symlink_to(outside)
        for url in (
            '/demo/snapshots/fault_0_early_body_before.jpg',
            '/demo/snapshots/../../secret.jpg',
            '/demo/snapshots/report.html',
            '/demo/snapshots/.oneclick-analysis.log',
            '/demo/snapshots/fault_0_unknown_code.jpg',
        ):
            with self.subTest(url=url):
                response = await self.request('GET', url)
                self.assertEqual(response.status_code, 404)

    async def test_visitor_cannot_read_prepared_only_images(self):
        (self.prepared.report.parent / 'seat_R1_catch.jpg').write_bytes(JPEG)
        only_prepared = f'/demo/videos/{self.visitor_id}/snapshots/seat_R1_catch.jpg'
        self.assertEqual((await self.request('GET', only_prepared)).status_code, 404)
        self.assertEqual((await self.request('GET', '/demo/snapshots/seat_R1_catch.jpg')).status_code, 200)


if __name__ == '__main__':
    unittest.main()
