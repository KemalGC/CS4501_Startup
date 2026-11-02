"""Duplicate crop proposals must not masquerade as additional rowers."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import multiframe


def skeleton(x, y=50., conf=.9):
    k=np.zeros((17,3),float)
    for i,dx,dy in [(0,0,-18),(5,-4,-8),(6,4,-8),(7,-6,0),(8,6,0),
                     (9,-9,8),(10,9,8),(11,-3,12),(12,3,12)]:
        k[i]=[x+dx,y+dy,conf]
    return k


class PoseMergeTests(unittest.TestCase):
    def merge(self, boxes, scores, keypoints):
        fn=getattr(multiframe,'merge_refined_detections',None)
        self.assertTrue(callable(fn),'crop merging must compare skeletons, not box overlap alone')
        return fn(np.asarray(boxes,float),np.asarray(scores,float),np.asarray(keypoints,float))

    def test_small_torso_crop_and_full_person_are_one_candidate(self):
        b,s,k=self.merge([[10,10,70,130],[15,10,65,65]],[.9,.8],
                        [skeleton(40),skeleton(41)])
        self.assertEqual(len(b),1)
        np.testing.assert_array_equal(b[0],[10,10,70,130])

    def test_overlapping_boxes_with_distinct_torsos_remain_two_people(self):
        b,s,k=self.merge([[10,10,90,130],[20,10,100,130]],[.9,.8],
                        [skeleton(30),skeleton(70)])
        self.assertEqual(len(b),2)

    def test_unrelated_skeletons_are_not_merged_by_containment(self):
        b,s,k=self.merge([[0,0,100,160],[20,20,65,85]],[.9,.8],
                        [skeleton(80,100),skeleton(40,50)])
        self.assertEqual(len(b),2)

    def test_low_confidence_joints_do_not_assert_anatomical_identity(self):
        b,s,k=self.merge([[0,0,60,150],[0,0,60,65]],[.9,.8],
                        [skeleton(30,conf=.1),skeleton(30,conf=.1)])
        self.assertEqual(len(b),2)

    def test_empty_and_malformed_detections_fail_predictably(self):
        b,s,k=self.merge(np.zeros((0,4)),np.zeros(0),np.zeros((0,17,3)))
        self.assertEqual(b.shape,(0,4))
        with self.assertRaises(ValueError):
            self.merge([[0,0,4,5]],[.9],np.zeros((1,16,3)))

    def test_deterministic_order_and_original_arrays_unchanged(self):
        boxes=np.array([[0,0,70,150],[1,1,69,149],[100,0,170,150]],float)
        points=np.array([skeleton(35),skeleton(35),skeleton(135)])
        old=boxes.copy(); pold=points.copy()
        a=self.merge(boxes,[.7,.9,.8],points)
        b=self.merge(boxes,[.7,.9,.8],points)
        np.testing.assert_array_equal(a[0],b[0])
        np.testing.assert_array_equal(a[1],[.9,.8])
        np.testing.assert_array_equal(boxes,old);np.testing.assert_array_equal(points,pold)

if __name__=='__main__':unittest.main()
