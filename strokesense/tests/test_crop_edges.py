"""Whole-body alternatives may replace truncated duplicates, never other rowers."""
import unittest
import numpy as np
from test_pose_merge import skeleton
from strokesense.pose_merge import merge_refined_detections,crop_edge_flags
from strokesense.pose import PoseDetector

class CropEdgeTests(unittest.TestCase):
    def pair(self,edge=(True,False),score=(.9,.85),quality=(.65,.95),offset=1):
        return merge_refined_detections(np.array([[10,10,60,100],[10,10,90,100.]]),
            np.array(score),np.array([skeleton(40,conf=quality[0]),skeleton(40+offset,conf=quality[1])]),crop_truncated=np.array(edge))

    def test_complete_stronger_torso_replaces_same_person_partial(self):
        b,s,k=self.pair();self.assertEqual(len(b),1);self.assertEqual(s[0],.85)
        np.testing.assert_array_equal(k[0],skeleton(41,conf=.95))

    def test_no_metadata_retains_score_order(self):
        b,s,k=self.pair(edge=(False,False));self.assertEqual(s[0],.9)

    def test_weak_complete_pose_cannot_replace_partial(self):
        for kwargs in [dict(score=(.9,.5)),dict(quality=(.8,.85)),dict(edge=(True,True)),dict(quality=(.1,.95))]:
            with self.subTest(kwargs=kwargs):
                b,s,k=self.pair(**kwargs);self.assertEqual(s[0],.9)

    def test_neighboring_torso_is_not_a_replacement(self):
        b,s,k=self.pair(offset=35);self.assertEqual(len(b),2)

    def test_partial_only_detection_survives(self):
        b,s,k=merge_refined_detections(np.array([[0,0,50,100.]]),np.array([.9]),np.array([skeleton(30)]),crop_truncated=np.array([True]))
        self.assertEqual(len(b),1);self.assertEqual(s[0],.9)

    def test_source_edges_are_not_crop_truncation(self):
        boxes=np.array([[0,0,100,100.],[10,10,60,60.]])
        np.testing.assert_array_equal(crop_edge_flags(boxes,(0,0,100,100),100,100),[False,False])
        np.testing.assert_array_equal(crop_edge_flags(boxes,(0,0,100,100),200,200),[True,False])
        np.testing.assert_array_equal(crop_edge_flags(boxes,(50,50,150,150),200,200),[True,False])

    def test_detector_passes_internal_crop_context(self):
        detector=PoseDetector.__new__(PoseDetector);detector.conf=.25;detector.iou=.5
        def infer(frame):
            width=frame.shape[1]
            if width==300:return np.zeros((0,4)),np.zeros(0),np.zeros((0,17,3))
            if width==100:return np.array([[70.,10,100,140]]),np.array([.9]),np.array([skeleton(90,conf=.65)])
            return np.array([[20.,10,80,140]]),np.array([.85]),np.array([skeleton(40,conf=.95)])
        detector._infer=infer
        b,s,k=detector(np.zeros((200,300,3),np.uint8),tiles=[(0,0,100,180),(50,0,200,180)])
        self.assertEqual(len(b),1);self.assertEqual(s[0],.85)
        expected=skeleton(40,conf=.95);expected[:,:2]+=[50,0]
        np.testing.assert_array_equal(k[0],expected)

    def test_invalid_metadata_is_rejected(self):
        for edge in [[True,False],[1]]:
            with self.assertRaises(ValueError):
                merge_refined_detections(np.array([[0,0,50,100.]]),np.array([.9]),np.array([skeleton(30)]),crop_truncated=edge)

if __name__=='__main__':unittest.main()
