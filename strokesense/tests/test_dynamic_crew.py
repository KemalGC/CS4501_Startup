"""Moving selected crew regressions; synthetic detections, not accuracy labels."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import cli, pose, report
from strokesense.selection import locked_tracks, SelectionError
from test_selected_crew import frame, selection
from synthetic import make_rower

META = {'width': 100, 'height': 100, 'fps': 15, 'start': 0, 'stride': 1}


def moved(dx=0, dy=0):
    b, k = frame(shift=dx)
    b[:, [1, 3]] += dy
    k[:, :, 1] += dy
    return b, k


def empty():
    return np.empty((0, 4)), np.empty((0, 17, 3))


class DynamicCrewTests(unittest.TestCase):
    def dynamic(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.dynamic_crew'),
                             'dynamic selected extraction/analysis is missing')
        from strokesense import dynamic_crew
        return dynamic_crew

    def test_one_exit_keeps_other_seven_and_does_not_recruit_other_boat(self):
        a, k = frame(); b, bk = frame(y=82)
        tracks = locked_tracks([(a, k), (np.vstack([a[:7], b]), np.vstack([k[:7], bk]))], META, selection())
        self.assertEqual(set(tracks), set(range(8)))
        np.testing.assert_array_equal(tracks[7]['frames'], [0])
        for i in range(7):
            np.testing.assert_array_equal(tracks[i]['frames'], [0, 1])
        result = pose.PoseResult(15, 2, 100, 100, tracks)
        self.assertTrue((result.dense(7)[1] == 0).all())

    def test_ambiguous_frame_is_gap_and_does_not_stop_other_tracks(self):
        a, k = frame(); duplicate = a[:1] + np.array([.1, 0, .1, 0])
        tracks = locked_tracks([(a, k), (np.vstack([a, duplicate]), np.vstack([k, k[:1]])), (a, k)], META, selection())
        np.testing.assert_array_equal(tracks[0]['frames'], [0, 2])
        for i in range(1, 8):
            np.testing.assert_array_equal(tracks[i]['frames'], [0, 1, 2])

    def test_follows_movement_beyond_original_boat_region(self):
        tracks = locked_tracks([moved(dy=i) for i in range(45)], META, selection())
        for track in tracks.values():
            self.assertEqual(len(track['frames']), 45)
            self.assertGreater(track['boxes'][-1, 1], 65)

    def test_short_gap_reacquires_motion_prediction_without_filling_missing_frames(self):
        dets = [moved(dx=i*2) for i in range(7)]
        for i in (3, 4):
            b, k = dets[i]; dets[i] = (b[1:], k[1:])
        tracks = locked_tracks(dets, META, selection())
        np.testing.assert_array_equal(tracks[0]['frames'], [0, 1, 2, 5, 6])
        self.assertAlmostEqual(tracks[0]['boxes'][-1, 0], 21)

    def test_all_exit_completes_and_long_absence_does_not_relabel_new_people(self):
        tracks = locked_tracks([frame()] + [empty() for _ in range(30)] + [frame()], META, selection())
        for track in tracks.values():
            np.testing.assert_array_equal(track['frames'], [0])

    def test_initial_missing_and_duplicate_targets_still_require_reselection(self):
        a, k = frame()
        for det in ((a[:7], k[:7]), (np.vstack([a, a[:1]]), np.vstack([k, k[:1]]))):
            with self.assertRaises(SelectionError):
                locked_tracks([det], META, selection())

    def test_extraction_uses_seed_crop_once_then_searches_full_frame(self):
        dynamic = self.dynamic(); seen = []
        class Capture:
            def isOpened(self): return True
            def get(self, key): return 15 if key == pose.cv2.CAP_PROP_FPS else 3
            def set(self, *args): pass
            def read(self): return True, np.zeros((100, 100, 3), np.uint8)
            def release(self): pass
        def detector(image, tiles=None):
            seen.append(image.shape)
            return np.array([[1., 2., 4., 5.]]), np.ones(1), np.ones((1, 17, 3))
        with patch.object(pose.cv2, 'VideoCapture', return_value=Capture()):
            dets, _ = dynamic.run_selected_video('synthetic', detector, selection(), tiles=None)
        self.assertEqual(seen, [(55, 96, 3), (100, 100, 3), (100, 100, 3)])
        np.testing.assert_array_equal(dets[0][0], [[3, 12, 6, 15]])
        np.testing.assert_array_equal(dets[1][0], [[1, 2, 4, 5]])

    def test_selected_cache_invalidates_fixed_crop_but_unselected_cache_stays_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp)/'synthetic.mov'; video.write_bytes(b'synthetic')
            old = json.loads(cli._cache_identity(video, 0, None, 'auto', 15, None))
            new = json.loads(cli._cache_identity(video, 0, None, 'auto', 15, None, selection=selection()))
        self.assertNotIn('selected_extraction', old['settings'])
        self.assertEqual(new['settings'].get('selected_extraction'), 'dynamic-full-frame-v2')

    def test_selected_strokes_never_span_missing_observations(self):
        dynamic = self.dynamic(); kp, fps = make_rower()
        keep = np.ones(len(kp), bool); keep[90:110] = False; keep[-40:] = False
        frames = np.flatnonzero(keep)
        p = pose.PoseResult(fps, len(kp), 1000, 1000, {0: {
            'frames': frames, 'boxes': np.tile([0, 0, 10, 10], (len(frames), 1)), 'kpts': kp[frames]}})
        r = dynamic.rowers_from_selected(p)[0]
        self.assertGreater(len(r.strokes), 0)
        for s in r.strokes:
            self.assertTrue(keep[s.catch:s.next_catch+1].all())
        coverage = r.summary['tracking']
        self.assertEqual(coverage['observed_frames'], int(keep.sum()))
        self.assertEqual(coverage['total_frames'], len(kp))
        self.assertEqual(r.seat, 'Selected 1')

    def test_no_usable_cycle_has_explicit_report_and_no_fake_score(self):
        dynamic = self.dynamic(); a, k = frame()
        tracks = locked_tracks([(a, k)] + [empty() for _ in range(45)], META, selection())
        p = pose.PoseResult(15, 46, 100, 100, tracks)
        rowers = dynamic.rowers_from_selected(p)
        self.assertEqual(len(rowers), 8)
        self.assertTrue(all(r.summary['n_strokes'] == 0 for r in rowers))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'report.html'
            report.build_html('synthetic', p, rowers, {}, {}, out)
            body = out.read_text()
        self.assertIn('Tracking coverage', body)
        self.assertIn('Insufficient continuous evidence', body)
        self.assertIn('1 / 46', body)
        self.assertNotIn('No consistent faults detected', body)


if __name__ == '__main__':
    unittest.main()
