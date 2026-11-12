"""Audit regressions: synthetic evidence, never a real-world accuracy claim."""
from pathlib import Path
import copy
import sys
from types import SimpleNamespace
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import kinematics, strokes, report, cadence, pose
from synthetic import make_rower
from test_pose_merge import skeleton


def timed_rower(i, offset=0., rate=30., cycles=5):
    period = 60/rate
    return SimpleNamespace(tid=i, seat=f'Selected {i+1}', k=SimpleNamespace(fps=30),
        strokes=[SimpleNamespace(rate=rate, catch_t=(offset+j*period)*30,
                    next_catch_t=(offset+(j+1)*period)*30,
                    catch=round((offset+j*period)*30), next_catch=round((offset+(j+1)*period)*30))
                 for j in range(cycles)])


class MeasurementQualityTests(unittest.TestCase):
    def test_low_confidence_is_not_an_observation_or_long_gap_estimate(self):
        kp, fps = make_rower(noise=0)
        kp[20:30, 9:11, 2] = .25
        k = kinematics.build(kp, fps)
        self.assertFalse(k.visible[20:30].any(), 'interpolated samples were counted observed')
        self.assertTrue(np.isnan(k.px['wrist'][20:30]).all(), 'long gaps must remain unavailable')

    def test_short_gap_provenance_is_distinct_and_no_edge_extrapolation(self):
        kp,fps=make_rower(noise=0)
        kp[40,9:11,2]=0;kp[:3,9:11,2]=0
        k=kinematics.build(kp,fps)
        self.assertTrue(hasattr(k,'observed') and hasattr(k,'estimated'),'sample provenance missing')
        self.assertFalse(k.observed['wrist'][40]);self.assertTrue(k.estimated['wrist'][40])
        self.assertFalse(k.visible[40]);self.assertTrue(np.isfinite(k.px['wrist'][40]).all())
        self.assertTrue(np.isnan(k.px['wrist'][:3]).all())

    def test_no_far_side_joint_splicing(self):
        kp,fps=make_rower(noise=0)
        kp[40,10,:2]=[0,0];kp[40,10,2]=0
        kp[40,9,:2]=[900,900];kp[40,9,2]=.9
        k=kinematics.build(kp,fps)
        self.assertLess(float(np.linalg.norm(k.px['wrist'][40]-kp[39,10,:2])),20,
                        'far-side point was spliced into the selected chain')

    def test_tiny_periodic_motion_is_not_strokes(self):
        n=450; fps=30; t=np.arange(n)/fps; phase=np.cos(2*np.pi*t/2.5)
        k=kinematics.Kinematics(fps,'right',1,50,visible=np.ones(n,bool),
            uv={'wrist':np.c_[phase*1e-5,np.zeros(n)]},
            reliable={'knee':True,'shoulder':True,'hip':True,'wrist':True},
            angles={'thigh':phase*.001,'trunk':phase*.001,'elbow':phase*.001})
        self.assertEqual(strokes.find_strokes(k)[0],[], 'negligible motion generated cycles')

    def test_unreliable_and_tiny_curves_are_unavailable(self):
        k=kinematics.Kinematics(30,'right',1,50,visible=np.ones(30,bool),
            reliable={'knee':False,'elbow':False,'shoulder':True,'hip':True},
            angles={name:np.linspace(0,.02,30) for name in ('thigh','trunk','elbow')})
        r=SimpleNamespace(k=k,strokes=[SimpleNamespace(catch=0,finish=29)])
        self.assertTrue(all(v is None for v in report.sequencing_curves(r).values()),
                        'unsupported .02-degree movement became a full curve')

    def test_curve_and_measurement_use_same_canonical_angles(self):
        kp,fps=make_rower(noise=0);k=kinematics.build(kp,fps); ss,_=strokes.analyse(k)
        self.assertGreaterEqual(len(ss),5)
        for s in ss:
            self.assertAlmostEqual(s.trunk_catch,float(k.angles['trunk'][s.catch]),places=10)
        r=SimpleNamespace(k=k,strokes=ss)
        self.assertTrue(hasattr(report,'sequencing_summary'),'per-signal counts/spread missing')
        summary=report.sequencing_summary(r)
        self.assertEqual(summary['body']['count'],len(ss))
        self.assertEqual(len(summary['body']['median']),50)

    def test_physical_trunk_angle_is_not_detrended(self):
        kp,fps=make_rower(n_strokes=14,noise=0)
        angle=np.linspace(-10,40,len(kp)); rad=np.radians(angle)
        for sh,hip in ((5,11),(6,12)):
            kp[:,sh,:2]=kp[:,hip,:2]+np.c_[55*np.sin(rad),-55*np.cos(rad)]
        k=kinematics.build(kp,fps)
        self.assertLess(np.max(np.abs(k.angles['trunk'][20:-20]-angle[20:-20])),.1,
                        'real slow posture change was removed as camera drift')

    def test_base_detector_preserves_two_overlapping_skeletons(self):
        d=pose.PoseDetector.__new__(pose.PoseDetector);d.conf=.25;d.iou=.5
        d._infer=lambda image:(np.array([[10,10,90,130],[20,10,100,130]],float),
                              np.array([.9,.8]),np.array([skeleton(30),skeleton(70)]))
        self.assertEqual(len(d(np.zeros((180,180,3),np.uint8))[0]),2)

    def test_shared_cadence_requires_simultaneous_events(self):
        people=[timed_rower(i,offset=i*30) for i in range(4)]
        self.assertIsNone(cadence.estimate(people)['rate_spm'],
                          'separate observation windows claimed shared cadence')

    def test_shared_five_cycle_timeline_retains_raw_outlier(self):
        people=[timed_rower(i,offset=i*.01) for i in range(4)]+[timed_rower(4,rate=45)]
        before=copy.deepcopy([vars(s) for r in people for s in r.strokes])
        result=cadence.estimate(people)
        self.assertIn('shared_cycles',result,'shared source-time interval evidence missing')
        self.assertEqual(len(result['shared_cycles']),5)
        self.assertAlmostEqual(result['rate_spm'],30,places=1)
        self.assertEqual(result['per_rower']['Selected 5']['raw_spm'],45)
        self.assertEqual(before,[vars(s) for r in people for s in r.strokes])

if __name__=='__main__':unittest.main()
