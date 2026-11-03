"""Dominant-crew isolation and evidence integrity; synthetic, not model accuracy."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def boxes(y=60,h=30,x=20,n=8,spacing=30):
    b=np.array([[x+i*spacing,y,x+i*spacing+18,y+h] for i in range(n)],float)
    k=np.zeros((n,17,3));k[:,:,2]=.9
    return b,k


class DominantCrewTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.dominant'), 'Dominant crew selection is missing')
        from strokesense import dominant
        return dominant
    def test_largest_clear_group_beats_smaller_background_group(self):
        m=self.module();a,k=boxes();b,q=boxes(y=10,h=14)
        groups=m.groups(np.vstack([b,a]),np.vstack([q,k]))
        chosen=m.choose_group(groups)
        self.assertEqual(set(chosen['members']),set(range(8,16)))
    def test_two_equally_sized_boats_do_not_merge(self):
        m=self.module();a,k=boxes();b,q=boxes(y=120)
        self.assertEqual(sorted(len(g['members']) for g in m.groups(np.vstack([a,b]),np.vstack([k,q]))),[8,8])
    def test_lost_foreground_never_substitutes_background(self):
        m=self.module();a,k=boxes();b,q=boxes(y=10,h=14)
        lock=m.CrewLock(m.choose_group(m.groups(a,k)),fps=10)
        result=lock.select(b,q)
        self.assertEqual(len(result),0)
    def test_follow_motion_but_retire_after_long_loss(self):
        m=self.module();a,k=boxes();lock=m.CrewLock(m.choose_group(m.groups(a,k)),fps=10)
        for i in range(12):
            b,q=boxes(x=20+i*3);self.assertEqual(len(lock.select(b,q)),8)
        for _ in range(25):lock.select(np.zeros((0,4)),np.zeros((0,17,3)))
        self.assertEqual(len(lock.select(*boxes(x=53))),0)
    def test_scene_jump_does_not_change_crew(self):
        m=self.module();a,k=boxes();lock=m.CrewLock(m.choose_group(m.groups(a,k)),fps=10)
        self.assertEqual(len(lock.select(*boxes(y=250))),0)
    def test_bidirectional_filter_keeps_reference_crew_only(self):
        m=self.module();a,k=boxes();b,q=boxes(y=10,h=14)
        dets=[(np.vstack([a,b]),np.vstack([k,q])) for _ in range(5)]
        clean,audit=m.isolate(dets,10,reference=2)
        self.assertTrue(all(len(z[0])==8 for z in clean))
        self.assertEqual(audit['excluded_detections'],40)
    def test_in_view_window_is_not_discarded_by_long_out_of_view_tail(self):
        m=self.module();a,k=boxes()
        # Enough real observations for slot initialization, followed by no people.
        # Confidence is valid and facing is unknown, not a fabricated cox label.
        dets=[(a.copy(),k.copy()) for _ in range(12)] + [(np.zeros((0,4)),np.zeros((0,17,3))) for _ in range(40)]
        self.assertTrue(hasattr(m,'track_visible_window'),'Long absence incorrectly dominates seat-count estimation')
        tracks,_,n=m.track_visible_window(dets,10)
        self.assertEqual(n,8)
        self.assertEqual(len(tracks),8)
        self.assertTrue(all(list(t['frames'])==list(range(12)) for t in tracks.values()))

    def test_validator_rejects_nonfinite_and_out_of_bounds_strokes(self):
        m=self.module()
        valid={'rowers':[{'tid':1,'seat':'R1','summary':{'n_strokes':1,'rate':30.},
                         'strokes':[{'catch':0,'finish':4,'next_catch':9}]}]}
        self.assertEqual(m.validate_metrics(valid,n_frames=20)['state'],'checks_passed')
        valid['rowers'][0]['summary']['rate']=float('nan')
        with self.assertRaises(ValueError):m.validate_metrics(valid,n_frames=20)
        valid['rowers'][0]['summary']['rate']=30.;valid['rowers'][0]['strokes'][0]['next_catch']=20
        with self.assertRaises(ValueError):m.validate_metrics(valid,n_frames=20)


if __name__=='__main__':unittest.main()
