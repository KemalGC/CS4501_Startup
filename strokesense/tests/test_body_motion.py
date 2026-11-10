"""Known-motion regressions; tests do not establish real-video accuracy."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import kinematics
from strokesense.body_motion import confidence_smooth
from synthetic import make_rower


class BodyMotionTests(unittest.TestCase):
    def test_equal_confidence_preserves_existing_zero_phase_filter(self):
        rng=np.random.default_rng(8);a=rng.normal(size=(100,2))
        np.testing.assert_allclose(confidence_smooth(a,np.ones(100)*.9,30),
                                   kinematics.smooth(a,30,.15),atol=1e-12)

    def test_isolated_confident_wrist_jump_is_estimated_not_observed(self):
        kp,fps=make_rower(noise=0);kp[100,10,:2]+=[65,-45]
        k=kinematics.build(kp,fps)
        self.assertTrue(k.rejected['wrist'][100]);self.assertFalse(k.observed['wrist'][100])
        self.assertTrue(k.estimated['wrist'][100]);self.assertFalse(k.visible[100])
        clean,_=make_rower(noise=0);gold=kinematics.build(clean,fps)
        self.assertLess(np.linalg.norm(k.px['wrist'][100]-gold.px['wrist'][100]),2)

    def test_camera_jolt_is_not_rejected_as_joint_error(self):
        kp,fps=make_rower(noise=0);kp[100,:,:2]+=[130,-75]
        k=kinematics.build(kp,fps)
        self.assertFalse(any(mask.any() for mask in k.rejected.values()))

    def test_body_motion_invariant_to_pan_with_varying_joint_confidence(self):
        kp,fps=make_rower(noise=0);t=np.arange(len(kp))
        for j in [6,8,10,12,14]:kp[:,j,2]=.65+.3*np.sin(t*.17+j)**2
        clean=kinematics.build(kp,fps)
        moved=kp.copy();moved[:,:,:2]+=np.c_[40*np.sin(t*.25)+t*.8,15*np.cos(t*.3)][:,None]
        result=kinematics.build(moved,fps)
        for name in ['trunk','elbow','thigh']:
            np.testing.assert_allclose(clean.angles[name],result.angles[name],atol=1e-9)
        np.testing.assert_allclose(clean.handle,result.handle,atol=1e-10)

    def test_hidden_feet_do_not_override_clear_body_side(self):
        kp,fps=make_rower(noise=0)
        kp[:,[5,7,9,11,13],2]=.7;kp[:,[6,8,10,12,14],2]=.75
        kp[:,15,2]=.99;kp[:,16,2]=.01
        self.assertEqual(kinematics.build(kp,fps).side,'right')

    def test_fast_clean_catches_and_real_posture_change_are_preserved(self):
        for fps in [15,30,60]:
            kp,_=make_rower(noise=0,rate=40,fps=fps)
            k=kinematics.build(kp,fps)
            self.assertFalse(any(mask.any() for mask in k.rejected.values()))
            self.assertGreater(np.ptp(k.angles['trunk']),49)

    def test_no_extrapolation_or_filtering_across_long_gap(self):
        kp,fps=make_rower(noise=0);kp[:4,10,2]=0;kp[100:115,10,2]=0
        k=kinematics.build(kp,fps)
        self.assertTrue(np.isnan(k.px['wrist'][:4]).all())
        self.assertTrue(np.isnan(k.px['wrist'][100:115]).all())
        cut=kinematics.sliced(k,95,120)
        np.testing.assert_array_equal(cut.rejected['wrist'],k.rejected['wrist'][95:120])

    def test_alternating_disagreement_is_not_arbitrarily_corrected(self):
        kp,fps=make_rower(noise=0)
        kp[100,10,:2]+=[50,-35];kp[102,10,:2]+=[50,-35]
        k=kinematics.build(kp,fps)
        self.assertFalse(k.rejected['wrist'][99:104].any())

    def test_input_arrays_are_unchanged(self):
        kp,fps=make_rower(noise=1);old=kp.copy();kinematics.build(kp,fps)
        np.testing.assert_array_equal(kp,old)

if __name__=='__main__':unittest.main()
