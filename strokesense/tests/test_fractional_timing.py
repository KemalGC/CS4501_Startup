"""Event-clock consistency and quantization against analytic motion."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense.kinematics import Kinematics
from strokesense import strokes, dynamic_crew
from synthetic import make_rower
from test_short_strokes import selected_pose


def sinusoid(fps,rate):
    t=np.arange(round(30*fps))/fps
    phase=np.cos(2*np.pi*rate/60*t+.37)
    return Kinematics(fps,'right',1,50,
        uv={'wrist':np.c_[1+phase,np.zeros(len(t))]},
        conf={'ankle':np.zeros(len(t))},
        reliable={'shoulder':True,'hip':True,'wrist':True,'knee':True,'elbow':True},
        visible=np.ones(len(t),bool),
        angles={'trunk':25*phase,'thigh':20+20*phase,'elbow':130+40*phase})


class FractionalTimingTests(unittest.TestCase):
    def test_analytic_rate_precision_improves_over_frame_quantization(self):
        for fps in [10,15,30]:
            for rate in [18.7,22.3,31.1,43.7]:
                with self.subTest(fps=fps,rate=rate):
                    found,_=strokes.analyse(sinusoid(fps,rate))
                    self.assertGreaterEqual(len(found),7)
                    old=np.array([60*fps/(s.next_catch-s.catch) for s in found])
                    new=np.array([s.rate for s in found])
                    self.assertLess(np.sqrt(np.mean((new-rate)**2)),.1*np.sqrt(np.mean((old-rate)**2)))

    def test_rates_and_durations_share_one_event_clock(self):
        found,_=strokes.analyse(sinusoid(15,22.3))
        for s in found:
            self.assertAlmostEqual(60/s.rate,s.drive_s+s.recovery_s,places=12)
            self.assertAlmostEqual(s.drive_s,(s.finish_t-s.catch_t)/15,places=12)
            self.assertAlmostEqual(s.recovery_s,(s.next_catch_t-s.finish_t)/15,places=12)
            self.assertLessEqual(abs(s.finish_t-s.finish),.5)
            self.assertAlmostEqual(s.ratio,s.recovery_s/s.drive_s,places=12)

    def test_fractional_finish_is_offset_with_segmented_track(self):
        kp,fps=make_rower(noise=0,n_strokes=10)
        keep=np.ones(len(kp),bool);keep[:100]=False;keep[250:270]=False
        row=dynamic_crew.rowers_from_selected(selected_pose(kp,fps,keep))[0]
        self.assertGreater(len(row.strokes),2)
        for s in row.strokes:
            self.assertGreater(s.finish_t,100)
            self.assertLessEqual(abs(s.finish_t-s.finish),.5)
            self.assertAlmostEqual(60/s.rate,(s.next_catch_t-s.catch_t)/fps,places=10)

if __name__=='__main__':unittest.main()
