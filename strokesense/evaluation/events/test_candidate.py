"""Analytic phase-specific finish checks, runnable before adopting the candidate."""
import importlib.util,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense.kinematics import Kinematics
modules={}
for name in ['baseline','candidate']:
    spec=importlib.util.spec_from_file_location('strokesense.phase_test_'+name,Path(__file__).with_name(name+'_strokes.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);modules[name]=module

def motion():
    t=np.arange(720);phase=(t%90)/90
    hand=np.cos(2*np.pi*phase)
    thigh=30*np.maximum(hand,-.2)-12*np.exp(-((phase-.61)/.06)**2)
    return Kinematics(30,'right',1,50,uv={'wrist':np.c_[hand,np.zeros(len(t))]},
        conf={},reliable={'knee':True,'wrist':True},visible=np.ones(len(t),bool),
        angles={'thigh':thigh,'trunk':30*hand},
        observed={'hip':np.ones(len(t),bool),'wrist':np.ones(len(t),bool),'knee':np.ones(len(t),bool)})

class PhaseFinishTests(unittest.TestCase):
    def test_knee_plateau_noise_cannot_shift_supported_hand_finish(self):
        k=motion();old,_,_=modules['baseline'].find_strokes(k);new,_,refined=modules['candidate'].find_strokes(k)
        self.assertGreaterEqual(len(new),6)
        self.assertEqual([(c,n) for c,_,n in old],[(c,n) for c,_,n in new])
        self.assertGreater(np.mean([abs(f%90-45) for _,f,_ in old]),3)
        for _,f,_ in new:
            self.assertEqual(f%90,45)
            self.assertAlmostEqual(refined[f],float(f))

    def test_unobserved_hand_reversal_does_not_override_mixed_cue(self):
        k=motion();k.observed['wrist'][np.arange(720)%90==45]=False
        old,_,_=modules['baseline'].find_strokes(k);new,_,_=modules['candidate'].find_strokes(k)
        self.assertEqual(old,new)

    def test_clean_aligned_cues_unchanged(self):
        k=motion();k.angles['thigh']=30*k.handle
        old,_,refold=modules['baseline'].find_strokes(k);new,_,refnew=modules['candidate'].find_strokes(k)
        self.assertEqual(old,new)
        for _,f,_ in new:self.assertAlmostEqual(refold[f],refnew[f])

if __name__=='__main__':unittest.main()
