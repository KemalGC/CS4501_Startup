"""Undefined projected geometry must not manufacture posture measurements."""
import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import kinematics,strokes
from synthetic import make_rower

class AngleGeometryTests(unittest.TestCase):
    def test_coincident_elbow_segments_are_unavailable(self):
        a=np.array([[0.,0.],[1.,0.],[1.,0.],[np.inf,0.]])
        b=np.zeros((4,2));c=np.array([[1.,0.],[0.,0.],[-1.,0.],[0.,1.]])
        result=kinematics.angle_at(a,b,c)
        self.assertTrue(np.isnan(result[[0,1,3]]).all())
        self.assertEqual(result[2],180.)

    def test_angles_are_scale_invariant(self):
        for scale in [1e-12,1.,1e12]:
            a=np.array([[1.,0.],[1.,0.],[1.,0.]])*scale
            b=np.zeros((3,2));c=np.array([[1.,0.],[0.,1.],[-1.,0.]])*scale
            np.testing.assert_allclose(kinematics.angle_at(a,b,c),[0,90,180],atol=1e-10)

    def test_zero_length_vertical_segment_is_not_upright(self):
        upper=np.array([[0.,0.],[0.,1.],[1.,0.],[np.inf,1.]])
        angle=kinematics.tilt_from_vertical(np.zeros_like(upper),upper)
        self.assertTrue(np.isnan(angle[[0,3]]).all())
        np.testing.assert_allclose(angle[[1,2]],[0,90])

    def test_collapsed_confident_torso_cannot_produce_strokes(self):
        kp,fps=make_rower(noise=0)
        kp[:,5,:2]=kp[:,11,:2];kp[:,6,:2]=kp[:,12,:2]
        k=kinematics.build(kp,fps)
        self.assertFalse(k.visible.any())
        self.assertTrue(np.isnan(k.angles['trunk']).all())
        self.assertEqual(strokes.analyse(k)[0],[])

if __name__=='__main__':unittest.main()
