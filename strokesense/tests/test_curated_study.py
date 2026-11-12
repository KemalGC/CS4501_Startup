"""Private eights packaging uses explicit diagnostics, never invented output."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.curated_study import build_eights_study
from strokesense.feedback import load_catalog
from strokesense.feedback_sharing import study_readiness


class EightsPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root/'runs'
        self.runs.mkdir()
        self.video = self.root/'synthetic.mp4'
        self.video.write_bytes(b'explicitly synthetic fixture, not playable media')
        self.poster = self.root/'poster.jpg'
        self.poster.write_bytes(b'explicitly synthetic image')
        self.selection = [dict(id=f'eight-{i}', title=f'Eight {i}', rowers=8,
            source=f'session/source-{i}.MOV', start=5., end=25., duration=20.,
            target='The eight-person crew; exclude its coxswain.',
            path=str(self.video), thumbnail=str(self.poster)) for i in range(5)]
        for item in self.selection:
            (self.runs/(item['id']+'.json')).write_text(json.dumps({
                'clip_id':item['id'], 'state':'unavailable', 'elapsed_seconds':0.1}))
        self.manifest = self.root/'selection.json'

    def build(self):
        self.manifest.write_text(json.dumps(self.selection))
        return build_eights_study(self.manifest, self.runs, self.root/'study')

    def completed_run(self):
        item = self.selection[0]
        inference = self.root/'inference.mp4'
        inference.write_bytes(b'Synthetic high-resolution inference input; different from preview')
        item['inference_sha256'] = hashlib.sha256(inference.read_bytes()).hexdigest()
        result = self.root/'results'/item['id']
        result.mkdir(parents=True)
        (result/'metrics.json').write_text(json.dumps({'rowers': [], 'evidence': {'status': 'synthetic'}}))
        (result/'report.html').write_text('<h1>Synthetic completed report</h1>')
        overlay = result/'annotated.mp4'
        overlay.write_bytes(b'Synthetic overlay, not playable media')
        run = {'clip_id': item['id'], 'state': 'completed', 'input': str(inference),
               'result_dir': str(result), 'annotated': str(overlay), 'elapsed_seconds': 0.1}
        record = self.runs/(item['id']+'.json')
        record.write_text(json.dumps(run))
        return inference, run, record

    def test_completed_run_requires_matching_selected_inference_bytes(self):
        inference, run, _ = self.completed_run()
        catalog = self.build()
        clip = catalog['clips'][0]
        self.assertEqual(clip['provenance']['inference_input_sha256'],
                         hashlib.sha256(inference.read_bytes()).hexdigest())
        self.assertEqual(clip['provenance']['inference_input_sha256'], self.selection[0]['inference_sha256'])
        self.assertEqual(clip['analysis']['status'], 'provisional')
        self.assertEqual(clip['analysis']['window'], {'start': 0., 'end': 20.})
        self.assertEqual((self.root/'study'/clip['report']).read_text(), '<h1>Synthetic completed report</h1>')
        self.assertEqual((self.root/'study'/clip['metrics']).read_bytes(),
                         (Path(run['result_dir'])/'metrics.json').read_bytes())
        self.assertTrue(study_readiness(self.root/'study', 5)['ready'])

    def test_same_clip_id_cannot_accept_another_inference_input(self):
        _, run, record = self.completed_run()
        other = self.root/'different-trim.mp4'
        other.write_bytes(b'Synthetic different crew or time window')
        run['input'] = str(other)
        record.write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, 'selected_inference_input_changed'):
            self.build()
        self.assertFalse((self.root/'study').exists())

    def test_completed_run_cannot_omit_or_malformed_selected_inference_hash(self):
        self.completed_run()
        for value in (None, '', 'not-a-sha256', 'g'*64, '0'*63, 123):
            with self.subTest(value=value):
                if value is None:
                    self.selection[0].pop('inference_sha256', None)
                else:
                    self.selection[0]['inference_sha256'] = value
                with self.assertRaisesRegex(ValueError, 'selection_inference_sha256_required'):
                    self.build()
                self.assertFalse((self.root/'study').exists())

    def test_completed_run_rejects_missing_or_empty_inference_input(self):
        _, run, record = self.completed_run()
        empty = self.root/'empty.mp4'
        empty.touch()
        for value in (None, '', str(self.root/'missing.mp4'), str(self.root), str(empty)):
            with self.subTest(value=value):
                data = dict(run)
                if value is None:
                    data.pop('input')
                else:
                    data['input'] = value
                record.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'completed_inference_input_required'):
                    self.build()
                self.assertFalse((self.root/'study').exists())

    def test_no_results_remain_diagnostics_without_made_up_metrics(self):
        self.build()
        catalog = load_catalog(self.root/'study/catalog.json')
        self.assertEqual(len(catalog['clips']), 5)
        for clip in catalog['clips']:
            self.assertEqual(clip['expected_rowers'], 8)
            self.assertEqual(clip['analysis']['status'], 'unavailable')
            self.assertEqual(clip['analysis']['aspects']['rate']['status'], 'unavailable')
            self.assertNotIn('metrics', clip)
            self.assertNotIn('annotated', clip)
            self.assertEqual(clip['analysis']['window'], {'start':0.,'end':20.})
            self.assertEqual(clip['provenance']['original_window_seconds']['start'], 5.)
        self.assertTrue(study_readiness(self.root/'study', 5)['ready'])
        self.assertFalse((self.root/'study/.feedback').exists())

    def test_four_or_single_is_rejected_before_any_study_is_written(self):
        self.selection[0]['rowers'] = 4
        with self.assertRaisesRegex(ValueError, 'eights_only'):
            self.build()
        self.assertFalse((self.root/'study').exists())

    def test_existing_study_is_never_replaced(self):
        self.build()
        marker = self.root/'study/keep-me.txt'
        marker.write_text('Existing participant records must survive')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertTrue(marker.is_file())

    def test_changed_selected_preview_is_rejected(self):
        self.selection[0]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'selected_preview_changed'):
            self.build()
        self.assertFalse((self.root/'study').exists())


if __name__ == '__main__':
    unittest.main()
