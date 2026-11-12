"""Synthetic regression tests for later-reference crew review (#100)."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.selection import validate_selection, locked_tracks, SelectionError
from test_selected_crew import frame, selection


class MultiFrameTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.multiframe'), 'multi-frame boat proposals are missing')
        from strokesense import multiframe
        return multiframe

    def test_reference_selection_is_versioned_and_strict(self):
        chosen = dict(selection(), version=2, reference_seconds=1.0)
        self.assertEqual(validate_selection(chosen)['reference_seconds'], 1)
        for value in (-1, float('nan'), float('inf'), True, 601):
            with self.subTest(value=value), self.assertRaises(SelectionError):
                validate_selection(dict(chosen, reference_seconds=value))
        with self.assertRaises(SelectionError): validate_selection(dict(selection(), reference_seconds=1))

    def test_later_reference_tracks_backward_and_forward_with_missing_initial_person(self):
        a, k = frame()
        dets = [(a[:7], k[:7]), (a, k), (a, k), (a[:6], k[:6])]
        chosen = dict(selection(), version=2, reference_seconds=1)
        result = locked_tracks(dets, {'width':100,'height':100,'fps':1}, chosen)
        np.testing.assert_array_equal(result[7]['frames'], [1,2])
        np.testing.assert_array_equal(result[0]['frames'], [0,1,2,3])

    def test_two_aligned_crews_produce_separate_suggested_boat_regions(self):
        m = self.module(); a, k = frame(); b, bk = frame(y=82)
        groups = m.boat_regions(np.vstack([a,b]), np.vstack([k,bk]), 100,100)
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(len(g['members']) for g in groups), [8,8])
        self.assertTrue(set(groups[0]['members']).isdisjoint(groups[1]['members']))
        self.assertEqual(groups[0]['kind'], 'rower_alignment_proposal')

    def test_refinement_merges_duplicates_and_keeps_coordinates_in_original_frame(self):
        m = self.module(); a,k = frame(); calls=[]
        def detector(image, tiles=None):
            calls.append(image.shape)
            if len(calls)==1: return a,k[:,0,2],k
            return np.zeros((0,4)), np.zeros(0), np.zeros((0,17,3))
        b,s,p = m.refined_detections(np.zeros((100,100,3),np.uint8), detector)
        self.assertGreater(len(calls),1)
        self.assertEqual(len(b),8)
        self.assertTrue(np.isfinite(p).all())
        self.assertLess(calls[1][0],calls[0][0])

    def test_scan_uses_later_frames_real_times_and_keeps_unselected_candidates(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'synthetic.avi'
            w=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(100,100))
            self.assertTrue(w.isOpened())
            for i in range(90): w.write(np.full((100,100,3),i,np.uint8))
            w.release(); seen=[]
            def proposal(image):
                seen.append(int(image.mean()));return {'state':'ready','candidates':[],'boats':[]}
            result=m.scan_clip(video, suggest_fn=proposal)
        self.assertEqual(len(result['frames']),5)
        self.assertEqual(result['frames'][0]['seconds'],0)
        self.assertGreater(result['frames'][-1]['seconds'],3)
        self.assertGreater(seen[-1],seen[0])
        self.assertTrue(all('data:image/jpeg;base64,' in f['image'] for f in result['frames']))
        self.assertEqual(result['selected'],[])

    def test_missing_model_stops_scan_with_honest_fallback(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'synthetic.avi';w=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(100,100))
            w.write(np.zeros((100,100,3),np.uint8));w.release()
            result=m.scan_clip(video, suggest_fn=lambda frame:{'state':'model_unavailable','candidates':[]})
        self.assertEqual(result['state'],'model_unavailable')
        self.assertEqual(len(result['frames']),1)

if __name__=='__main__': unittest.main()
