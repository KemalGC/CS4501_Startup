"""Three actual, time-spaced visible poses for a measured candidate fault."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import cv2  # noqa: F401 - render.py requires the real OpenCV package
except ModuleNotFoundError:
    cv2 = None


@unittest.skipIf(cv2 is None, 'OpenCV is not installed in this runtime')
class MistakeProgressionTests(unittest.TestCase):
    def test_visible_before_at_after_frames_are_measured_and_time_spaced(self):
        from strokesense import render

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            visible = np.ones(80, dtype=bool)
            rower = SimpleNamespace(
                tid=0, k=SimpleNamespace(n=80, visible=visible),
                summary={'issues': [{'code': 'early_body'}, {'code': 'short_catch'}]},
            )
            pose = SimpleNamespace(start=9.0, fps=15.0)
            faults = {'early_body': {'frame': 30, 'stroke': 4,
                                     'path': root / 'fault_0_early_body.jpg'}}
            seq, requests = render.mistake_progression_requests(rower, pose, faults, root)
            self.assertEqual(len(seq), 1)
            self.assertEqual(seq[0]['code'], 'early_body')
            self.assertEqual(seq[0]['stroke'], 4)
            self.assertEqual([f['frame'] for f in seq[0]['frames']], [27, 30, 33])
            self.assertEqual([f['label'] for f in seq[0]['frames']],
                             ['Before', 'Flagged moment', 'After'])
            self.assertEqual(len(requests), 2)
            self.assertEqual([r[0] for r in requests], [27, 33])
            for frame in seq[0]['frames']:
                self.assertAlmostEqual(frame['time_seconds'], 9 + frame['frame'] / 15)

    def test_invisible_context_is_never_exposed_or_reassigned(self):
        from strokesense import render

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            visible = np.zeros(80, dtype=bool)
            visible[30] = True
            rower = SimpleNamespace(
                tid=5, k=SimpleNamespace(n=80, visible=visible),
                summary={'issues': [{'code': 'early_body'}]},
            )
            pose = SimpleNamespace(start=0., fps=15.)
            faults = {'early_body': {'frame': 30, 'stroke': 3,
                                     'path': root / 'fault_5_early_body.jpg'}}
            seq, requests = render.mistake_progression_requests(rower, pose, faults, root)
            self.assertEqual(len(seq[0]['frames']), 1)
            self.assertEqual(requests, [])

    def test_manifest_only_lists_images_written_by_current_renderer(self):
        from strokesense import cli

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catch = root / 'seat_R1_catch.jpg'
            finish = root / 'seat_R1_finish.jpg'
            missing = root / 'fault_0_early_body.jpg'
            before = root / 'fault_0_early_body_before.jpg'
            rower = SimpleNamespace(tid=0, seat='R1')
            snaps = {0: {
                'catch': catch, 'catch_seconds': 2.0,
                'finish': finish, 'finish_seconds': 2.5,
                'progressions': [{'code': 'early_body', 'stroke': 4,
                                  'frames': [
                                      {'label': 'Before', 'time_seconds': 1.8, 'path': before},
                                      {'label': 'Flagged moment', 'time_seconds': 2.0, 'path': missing},
                                  ]}],
            }}
            cli._write_mistake_gallery(root, [rower], snaps, {catch, before})
            payload = json.loads((root / 'mistake_frames.json').read_text())
            photos = payload['rowers']['R1']
            self.assertEqual([p['filename'] for p in photos['snapshots']], [catch.name])
            self.assertEqual(photos['mistake_sequences'], [])
            self.assertNotIn(missing.name, json.dumps(payload))


if __name__ == '__main__':
    unittest.main()
