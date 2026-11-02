"""Synthetic phase/gap tests: not detector or coaching accuracy measurements."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import dynamic_crew, kinematics, strokes, report
from strokesense.pose import PoseResult
from synthetic import make_rower


def selected_pose(kp, fps, keep=None):
    keep = np.ones(len(kp), bool) if keep is None else keep
    frames = np.flatnonzero(keep)
    return PoseResult(fps, len(kp), 1000, 1000, {0: {
        'frames': frames, 'boxes': np.tile([0,0,10,10], (len(frames),1)), 'kpts': kp[frames]}})


class ShortStrokeTests(unittest.TestCase):
    def test_brief_internal_drops_do_not_destroy_every_cycle(self):
        kp, fps = make_rower(n_strokes=8, rate=30, noise=0)
        keep = np.ones(len(kp), bool)
        keep[40::60] = False
        rower = dynamic_crew.rowers_from_selected(selected_pose(kp, fps, keep))[0]
        self.assertGreaterEqual(len(rower.strokes), 5, 'one-frame dropouts fragment all complete cycles')
        self.assertEqual(rower.summary['assessment']['state'], 'short_assessment_ready')
        self.assertEqual(rower.summary['tracking']['observed_frames'], int(keep.sum()))
        self.assertTrue(np.isnan(rower.k.px['wrist'][~keep]).all())
        self.assertTrue(any(s.gap_frames > 0 for s in rower.strokes))
        for s in rower.strokes:
            self.assertTrue(keep[[s.catch,s.finish,s.next_catch]].all())
            self.assertEqual(s.gap_frames, int((~keep[s.catch:s.next_catch+1]).sum()))

    def test_long_absence_still_splits_cycles_and_no_extrapolation(self):
        kp, fps = make_rower(n_strokes=8, rate=30, noise=0)
        keep = np.ones(len(kp), bool);keep[:20]=False;keep[100:130]=False;keep[-25:]=False
        r = dynamic_crew.rowers_from_selected(selected_pose(kp, fps, keep))[0]
        for s in r.strokes:
            self.assertTrue(keep[s.catch:s.next_catch+1].all())
        self.assertTrue(np.isnan(r.k.px['wrist'][~keep]).all())

    def test_parallel_cycles_equal_serial_and_remain_ordered(self):
        kp,fps=make_rower(n_strokes=8,rate=30,noise=0)
        k=kinematics.build(kp,fps)
        self.assertIn('workers',__import__('inspect').signature(strokes.analyse).parameters,
                      'independent cycle worker control is missing')
        serial,_=strokes.analyse(k,workers=1)
        with patch('strokesense.strokes.ThreadPoolExecutor',wraps=__import__('concurrent.futures',fromlist=['ThreadPoolExecutor']).ThreadPoolExecutor) as pool:
            parallel,_=strokes.analyse(k,workers=4)
        self.assertTrue(pool.called)
        self.assertEqual([s.to_dict() for s in serial],[s.to_dict() for s in parallel])
        self.assertEqual([s.idx for s in parallel],list(range(len(parallel))))
        for invalid in (0,5,True,1.5):
            with self.assertRaises(ValueError):strokes.analyse(k,workers=invalid)

    def test_five_cycles_is_enough_not_five_required_for_any_data(self):
        kp,fps=make_rower(n_strokes=9,rate=30,noise=0)
        ss,_=strokes.analyse(kinematics.build(kp,fps));self.assertGreaterEqual(len(ss),5)
        five=strokes.summarise(ss[:5]);one=strokes.summarise(ss[:1])
        self.assertIn('assessment',five,'five-stroke sample policy is missing')
        self.assertEqual(five['assessment']['state'],'short_assessment_ready')
        self.assertEqual(one['assessment']['state'],'preliminary')
        self.assertIsNone(one['consistency'],'one cycle cannot establish 100/100 consistency')

    def test_short_gap_quality_never_scores_missing_landmarks(self):
        kp,fps=make_rower(n_strokes=8,rate=30,noise=0)
        clean,_=strokes.analyse(kinematics.build(kp,fps))
        keep=np.ones(len(kp),bool)
        for s in clean:keep[s.finish]=False
        r=dynamic_crew.rowers_from_selected(selected_pose(kp,fps,keep))[0]
        for s in r.strokes:self.assertTrue(keep[[s.catch,s.finish,s.next_catch]].all())


if __name__=='__main__':unittest.main()
