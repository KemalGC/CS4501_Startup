"""Resume regressions: consistent refined detections, separate boats, browser CSP."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import dynamic_crew, multiframe, pose
from test_selected_crew import frame, selection
import test_review_routes as fixtures


class TemporalHandoffTests(unittest.TestCase):
    def test_refinement_is_consistent_before_and_after_reference(self):
        chosen = dict(selection(), version=2, reference_seconds=1.0)
        images = [np.zeros((100, 100, 3), np.uint8) for _ in range(3)]
        boxes, keypoints = frame()
        detections = (boxes, np.ones(8), keypoints)
        def fake_run(video, detect, **kwargs):
            return [detect(image) for image in images], {}
        class Capture:
            def get(self, key): return 1.0
            def release(self): pass
        with patch.object(pose.cv2, 'VideoCapture', return_value=Capture()), \
             patch.object(pose, 'run_video', side_effect=fake_run), \
             patch.object(multiframe, 'refined_detections', return_value=detections) as refined:
            dynamic_crew.run_selected_video('synthetic', lambda *a, **k: detections,
                                           chosen, target_fps=1)
        self.assertEqual(refined.call_count, 3,
                         'Higher-detail rowers must not vanish outside the reference frame')

    def test_collinear_distant_crews_are_not_one_boat_proposal(self):
        a, points = frame()
        b = a + np.array([150., 0., 150., 0.])
        groups = multiframe.boat_regions(np.vstack([a, b]), None, 260, 100)
        self.assertEqual(len(groups), 2, 'A large gap must split aligned boat proposals')
        self.assertEqual(sorted(len(g['members']) for g in groups), [8, 8])
        self.assertTrue(set(groups[0]['members']).isdisjoint(groups[1]['members']))

    def test_review_allows_only_same_origin_status_fetch(self):
        server_test = fixtures.ReviewHTTPTests()
        server_test.setUp()
        self.addCleanup(server_test.doCleanups)
        status, headers, _ = server_test.request('GET', '/review?clip=' + server_test.cid)
        self.assertEqual(status, 200)
        policy = headers['Content-Security-Policy']
        self.assertIn("connect-src 'self'", policy,
                      'Browser polling is otherwise blocked by default-src none')
        self.assertIn("default-src 'none'", policy)
        self.assertNotIn('connect-src *', policy)


if __name__ == '__main__':
    unittest.main()
