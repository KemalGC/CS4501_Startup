"""Configured study size and honest diagnostic readiness through the gateway."""
import io
import json
import unittest
import zipfile
from pathlib import Path
import test_hosted as fixtures
from test_tester_links import ten_package
from strokesense.feedback_sharing import study_readiness


class CuratedStudyTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.HostedTests()
        self.base.expected_clips = 7
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.c = self.base.client

    def test_seven_clip_pack_is_ready_and_invitable(self):
        self.assertEqual(self.base.upload(ten_package(count=7)).status_code, 201)
        health = self.c.get('/healthz').json()
        self.assertEqual((health['study_ready'], health['clip_count'], health['expected_clips']), (True, 7, 7))
        result = self.c.get('/api/owner/invitation', headers={'Authorization':'Bearer '+fixtures.OWNER})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['readiness']['report_count'], 7)

    def test_wrong_size_and_missing_assets_do_not_claim_health_readiness(self):
        self.assertEqual(self.base.upload(ten_package(count=6)).status_code, 201)
        self.assertFalse(self.c.get('/healthz').json()['study_ready'])
        result = self.c.get('/api/owner/invitation', headers={'Authorization':'Bearer '+fixtures.OWNER})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['readiness']['expected_clips'], 7)

    def test_removed_declared_overlay_is_not_ready(self):
        self.base.upload(ten_package(count=7))
        (self.base.root/'study/media/overlay.mp4').unlink()
        self.assertFalse(self.c.get('/healthz').json()['study_ready'])

    def test_declared_saved_metrics_survive_hosted_provisioning(self):
        # The same pack also imports into the normal analysis library. Keep
        # its declared measurements intact without adding a public raw-data route.
        source = io.BytesIO(ten_package(count=7))
        out = io.BytesIO()
        metrics = b'{"rowers": {}, "fixture": "saved-output"}'
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(out, 'w') as new:
            for entry in old.infolist():
                data = old.read(entry)
                if entry.filename.endswith('/catalog.json'):
                    catalog = json.loads(data)
                    catalog['clips'][0]['metrics'] = 'results/clip-1/metrics.json'
                    data = json.dumps(catalog).encode()
                new.writestr(entry.filename, data)
            new.writestr('Study/study/results/clip-1/metrics.json', metrics)
        self.assertEqual(self.base.upload(out.getvalue()).status_code, 201)
        self.assertEqual((self.base.root/'study/results/clip-1/metrics.json').read_bytes(), metrics)
        self.assertTrue(self.c.get('/healthz').json()['study_ready'])

    def test_diagnostic_can_explicitly_withhold_overlay(self):
        self.base.upload(ten_package(count=7))
        root = self.base.root/'study'
        catalog = json.loads((root/'catalog.json').read_text())
        clip = catalog['clips'][0]
        clip.pop('annotated')
        clip['analysis']['status'] = 'unavailable'
        (root/'catalog.json').write_text(json.dumps(catalog))
        self.assertTrue(study_readiness(root, 7)['ready'])
        # A live process cannot silently relabel an already-loaded analysis.
        self.assertFalse(self.c.get('/healthz').json()['study_ready'])


if __name__ == '__main__':
    unittest.main()
