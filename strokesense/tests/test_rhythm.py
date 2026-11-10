"""Rhythm evidence must retain elapsed source time across missing samples."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import strokes, crew, kinematics
from synthetic import make_rower


def original(values,fps):
    x=values-values.mean();ac=np.correlate(x,x,'full')[len(x)-1:];ac/=ac[0]
    return float(ac[int(fps*60/50):min(len(ac)-1,int(fps*60/12))].max())


class RhythmTests(unittest.TestCase):
    def test_complete_signal_retains_existing_strength(self):
        t=np.arange(600)/30
        for values in [np.cos(t*2*np.pi/2.7),np.random.default_rng(42).normal(size=len(t))]:
            self.assertAlmostEqual(strokes.periodicity(values,30),max(0,original(values,30)),places=12)

    def test_missing_samples_do_not_destroy_detectable_rhythm(self):
        t=np.arange(900)/30;full=np.cos(2*np.pi*t/2.7)
        missing=full.copy();missing[np.random.default_rng(83).random(len(t))<.35]=np.nan
        self.assertGreater(strokes.periodicity(missing,30),.7)
        self.assertLess(abs(strokes.periodicity(full,30)-strokes.periodicity(missing,30)),.15)

    def test_leading_and_trailing_absence_does_not_change_strength(self):
        x=np.cos(np.arange(600)*2*np.pi/81)
        self.assertAlmostEqual(strokes.periodicity(np.r_[np.full(300,np.nan),x,np.full(100,np.nan)],30),
                               strokes.periodicity(x,30),places=12)

    def test_unsupported_or_constant_inputs_are_unavailable(self):
        for x in [np.array([]),np.full(400,np.nan),np.ones(400),np.r_[np.arange(10),np.full(400,np.nan)]]:
            self.assertEqual(strokes.periodicity(x,30),0.)

    def test_segmentation_passes_full_length_and_observed_mask(self):
        kp,fps=make_rower(noise=0);kp[60:90,9:11,2]=0
        k=kinematics.build(kp,fps)
        with patch.object(strokes,'periodicity',wraps=strokes.periodicity) as fn:
            strokes.find_strokes(k)
        self.assertTrue(fn.called)
        self.assertTrue(all(len(call.args[0])==k.n for call in fn.call_args_list))
        self.assertTrue(np.isnan(fn.call_args_list[0].args[0][60:90]).all())

    def test_single_rower_and_crew_share_quality_policy(self):
        x=np.sin(np.arange(500)/10);x[100:130]=np.nan
        self.assertEqual(crew._periodicity(x,15),strokes.periodicity(x,15))

    def test_invalid_settings_fail_predictably(self):
        for fps in [0,-1,np.nan]:
            with self.assertRaises(ValueError):strokes.periodicity(np.arange(300),fps)
        with self.assertRaises(ValueError):strokes.periodicity(np.arange(300),15,50,12)

if __name__=='__main__':unittest.main()
