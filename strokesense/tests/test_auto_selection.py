"""Automatic confirmation: synthetic detections only, never model/network calls."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import selection_ui
from strokesense.selection import locked_tracks
import test_web as fixture


def detections():
    boxes = np.array([[10+i*22, y, 26+i*22, y+25] for y in (20, 100) for i in range(8)], float)
    k = np.ones((16, 17, 3))
    return boxes, np.ones(16), k


class AutoSelectionTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.auto_selection'),
                             'automatic candidate detection is missing')
        from strokesense import auto_selection
        return auto_selection

    def test_two_boats_are_candidates_not_automatically_selected(self):
        m = self.module(); calls = []
        def detector(frame, tiles=None):
            calls.append((frame.shape, tiles)); return detections()
        data = m.detect_candidates(np.zeros((160, 200, 3), np.uint8), detector)
        self.assertEqual(data['state'], 'ready')
        self.assertEqual(len(data['candidates']), 16)
        self.assertTrue(calls[0][1])
        self.assertNotIn('selected', data)
        self.assertEqual([c['id'] for c in data['candidates']], list(range(1, 17)))
        self.assertTrue(all(c['seed'] is not None for c in data['candidates']))

    def test_detector_anchors_roundtrip_into_existing_closed_crew_contract(self):
        m = self.module(); b, scores, k = detections()
        data = m.detect_candidates(np.zeros((160, 200, 3), np.uint8), lambda *a, **kw: (b, scores, k))
        crew = {'version': 1, 'roi': [0, 0, 1, 1],
                'seeds': [c['seed'] for c in data['candidates'][:8]], 'confirmed_same_boat': True}
        tracks = locked_tracks([(b, k)], {'width': 200, 'height': 160}, crew)
        self.assertEqual(len(tracks), 8)
        self.assertTrue(all(t['boxes'][0, 1] == 20 for t in tracks.values()))

    def test_duplicated_overlapping_boxes_cannot_offer_ambiguous_anchors(self):
        m = self.module(); b, scores, k = detections()
        b[1] = b[0]
        data = m.detect_candidates(np.zeros((160, 200, 3), np.uint8), lambda *a, **kw: (b, scores, k))
        self.assertEqual(sum(c['seed'] is None for c in data['candidates']), 2)

    def test_invalid_and_low_quality_detections_are_not_candidates(self):
        m = self.module(); b, scores, k = detections()
        b[0, 0] = float('nan'); b[1, 2] = b[1, 0]; k[2, 5:13, 2] = 0
        data = m.detect_candidates(np.zeros((160, 200, 3), np.uint8), lambda *a, **kw: (b, scores, k))
        self.assertEqual(len(data['candidates']), 13)
        self.assertTrue(all(np.isfinite(c['box']).all() for c in data['candidates']))

    def test_empty_and_excessive_detections_are_bounded_and_honest(self):
        m = self.module()
        for count, state in ((0, 'no_detections'), (65, 'too_many')):
            with self.subTest(count=count):
                b = np.tile([1, 1, 20, 20], (count, 1)); k = np.ones((count, 17, 3))
                data = m.detect_candidates(np.zeros((160, 200, 3), np.uint8), lambda *a, **kw: (b, np.ones(count), k))
                self.assertEqual(data, {'state': state, 'candidates': []})

    def test_preview_resize_matches_analysis_resize(self):
        m = self.module(); seen = []
        def detector(frame, tiles=None):
            seen.append(frame.shape); return np.zeros((0, 4)), np.zeros(0), np.zeros((0, 17, 3))
        m.detect_candidates(np.zeros((1080, 2560, 3), np.uint8), detector)
        self.assertEqual(seen, [(810, 1920, 3)])

    def test_missing_model_never_downloads_or_constructs_detector(self):
        m = self.module()
        with patch.object(m, 'DEFAULT_MODEL', Path('/not/a/cached/model.onnx')), patch.object(m, 'PoseDetector') as detector:
            data = m.suggest(np.zeros((160, 200, 3), np.uint8))
        self.assertEqual(data['state'], 'model_unavailable'); detector.assert_not_called()

    def test_busy_preview_does_not_launch_concurrent_model_work(self):
        m = self.module()
        with m.DETECTION_LOCK:
            data = m.suggest(np.zeros((160, 200, 3), np.uint8))
        self.assertEqual(data['state'], 'busy')

    def test_preview_carries_detections_to_accessible_unchecked_controls(self):
        m = self.module(); cap = MagicMock(); cap.isOpened.return_value = True
        cap.read.return_value = (True, np.zeros((160, 200, 3), np.uint8))
        data = m.detect_candidates(cap.read.return_value[1], lambda *a, **kw: detections())
        with patch('cv2.VideoCapture', return_value=cap), patch.object(m, 'suggest', return_value=data):
            image = selection_ui.preview_jpeg('synthetic')
        body = selection_ui.selection_form('a'*64, 'safe-test-token', image)
        self.assertIn('Detected people', body); self.assertIn('data-candidates=', body)
        self.assertIn('Use manual selection', body); self.assertIn('name="same_boat"', body)
        self.assertNotIn('checked', body)
        self.assertIn('0 of 8', body)
        cap.release.assert_called_once()


class AutoSelectionHTTPTests(unittest.TestCase):
    setUp = fixture.LocalWebTests.setUp
    _stop = fixture.LocalWebTests._stop
    request = fixture.LocalWebTests.request

    def test_private_preview_displays_candidates_without_launching_analysis(self):
        m = AutoSelectionTests().module(); cap = MagicMock(); cap.isOpened.return_value = True
        cap.read.return_value = (True, np.zeros((160, 200, 3), np.uint8))
        data = m.detect_candidates(cap.read.return_value[1], lambda *a, **kw: detections())
        with patch('cv2.VideoCapture', return_value=cap), patch.object(m, 'suggest', return_value=data):
            code, headers, body = self.request('GET', '/select?clip='+self.clip_id)
        self.assertEqual(code, 200); self.assertIn(b'Detected people', body)
        self.assertEqual(self.worker.list_recent(), [])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn(str(self.video).encode(), body)

    def test_revoked_preview_never_calls_detection(self):
        m = AutoSelectionTests().module()
        from strokesense.registry import revoke_clip
        revoke_clip(self.clip_id, self.registry_db)
        with patch.object(m, 'suggest') as detect:
            self.assertEqual(self.request('GET', '/select?clip='+self.clip_id)[0], 403)
        detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
