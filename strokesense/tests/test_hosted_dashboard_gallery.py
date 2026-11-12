"""Measured-event galleries expose only genuine, bounded report-side JPEGs."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.hosted_dashboard import build_dashboard


class HostedGalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / 'current-run'
        self.run.mkdir()
        self.report = self.run / 'report.html'
        self.report.write_text('<h1>Test report</h1>', encoding='utf-8')
        self.metrics = {
            'crew_cadence': {'rate_spm': 31.1},
            'rowers': [{'seat': 'R1', 'track': 0, 'strokes': [{}, {}, {}], 'summary': {
                'n_strokes': 3,
                'issues': [{'code': 'early_body', 'title': 'Opening the back too early',
                            'frac': 1 / 3}],
            }}, {'seat': 'R2', 'track': 1, 'strokes': [], 'summary': {'n_strokes': 0}}],
        }
        self._save_metrics()

    def tearDown(self):
        self.temp.cleanup()

    def _save_metrics(self):
        (self.run / 'metrics.json').write_text(json.dumps(self.metrics), encoding='utf-8')

    def _photo(self, name):
        (self.run / name).write_bytes(b'\xff\xd8\xff\xd9')

    def _dashboard(self):
        state = SimpleNamespace(
            snapshot=lambda: {'state': 'finished'}, report=self.report,
            output_root=self.root, run_id='f' * 32, last_end=None)
        return build_dashboard(
            state, 'Uploaded clip',
            snapshots_base='/demo/videos/' + 'b' * 48 + '/snapshots')

    def test_real_flagged_progression_has_correct_image_urls_and_times(self):
        names = [
            'fault_0_early_body_before.jpg', 'fault_0_early_body.jpg',
            'fault_0_early_body_after.jpg', 'seat_R1_catch.jpg',
        ]
        for name in names:
            self._photo(name)
        frames = [
            {'label': label, 'time_seconds': t, 'filename': name}
            for label, t, name in zip(
                ['Before', 'Flagged moment', 'After'],
                [2.2, 2.4, 2.6], names[:3])
        ]
        (self.run / 'mistake_frames.json').write_text(json.dumps({
            'version': 1, 'rowers': {'R1': {
                'mistake_sequences': [{'code': 'early_body', 'stroke': 2,
                                       'frames': frames}],
                'snapshots': [{'label': 'Catch reference', 'time_seconds': 3.3,
                               'filename': names[3]}],
            }},
        }), encoding='utf-8')
        rower = self._dashboard()['rowers'][0]
        sequence = rower['mistake_sequences'][0]
        self.assertEqual(sequence['label'], 'Opening the back too early')
        self.assertEqual(sequence['stroke'], 2)
        self.assertEqual([f['label'] for f in sequence['frames']],
                         ['Before', 'Flagged moment', 'After'])
        self.assertEqual([f['time_seconds'] for f in sequence['frames']],
                         [2.2, 2.4, 2.6])
        self.assertTrue(all(f['url'].startswith('/demo/videos/' + 'b' * 48 + '/snapshots/')
                            for f in sequence['frames']))
        self.assertEqual(len(rower['snapshots']), 1)

    def test_missing_or_unmeasured_frames_never_appear(self):
        self._photo('fault_0_early_body.jpg')
        self._photo('fault_0_short_catch.jpg')
        (self.run / 'mistake_frames.json').write_text(json.dumps({
            'version': 1, 'rowers': {'R1': {
                'mistake_sequences': [
                    {'code': 'early_body', 'stroke': 1, 'frames': [
                        {'label': 'Flagged moment', 'time_seconds': 1.2,
                         'filename': 'fault_0_early_body.jpg'},
                        {'label': 'After', 'time_seconds': 1.4,
                         'filename': 'fault_0_early_body_after.jpg'},
                        {'label': 'Before', 'time_seconds': 1.,
                         'filename': '../../private.jpg'},
                    ]},
                    {'code': 'short_catch', 'stroke': 1, 'frames': [
                        {'label': 'Flagged moment', 'time_seconds': 1.2,
                         'filename': 'fault_0_short_catch.jpg'},
                    ]},
                ], 'snapshots': [],
            }},
        }), encoding='utf-8')
        rower = self._dashboard()['rowers'][0]
        self.assertEqual(len(rower['mistake_sequences']), 1)
        self.assertEqual(len(rower['mistake_sequences'][0]['frames']), 1)
        self.assertEqual(rower['mistake_sequences'][0]['frames'][0]['label'], 'Flagged moment')

    def test_old_completed_run_exposes_actual_flag_still_and_catch_finish(self):
        self._photo('fault_0_early_body.jpg')
        self._photo('seat_R1_catch.jpg')
        self._photo('seat_R1_finish.jpg')
        rower = self._dashboard()['rowers'][0]
        self.assertEqual(rower['mistake_sequences'], [])
        self.assertEqual(len(rower['snapshots']), 3)
        self.assertIn('Opening the back too early', rower['snapshots'][0]['label'])
        self.assertEqual(rower['snapshots'][0]['time_seconds'], None)

    def test_malformed_manifest_cannot_attribute_another_rowers_photos(self):
        self._photo('fault_1_early_body.jpg')
        self._photo('seat_R2_catch.jpg')
        (self.run / 'mistake_frames.json').write_text(json.dumps({
            'version': 1, 'rowers': {'R1': {
                'mistake_sequences': [{'code': 'early_body', 'stroke': 1, 'frames': [
                    {'label': 'Flagged moment', 'time_seconds': 1.2,
                     'filename': 'fault_1_early_body.jpg'},
                ]}],
                'snapshots': [{'label': 'Catch reference', 'time_seconds': 1.1,
                               'filename': 'seat_R2_catch.jpg'}],
            }},
        }), encoding='utf-8')
        rower = self._dashboard()['rowers'][0]
        self.assertEqual(rower['mistake_sequences'], [])
        self.assertEqual(rower['snapshots'], [])

    def test_symlink_or_oversize_image_is_not_shared(self):
        outside = self.root / 'outside.jpg'
        outside.write_bytes(b'\xff\xd8\xff\xd9')
        (self.run / 'seat_R1_catch.jpg').symlink_to(outside)
        (self.run / 'seat_R1_finish.jpg').write_bytes(b'0' * (512 * 1024 + 1))
        rower = self._dashboard()['rowers'][0]
        self.assertEqual(rower['snapshots'], [])


if __name__ == '__main__':
    unittest.main()
