"""User-selected crew behavior; synthetic detections, no network/model."""
import copy
import importlib.util
import inspect
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import cli, pose
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip


def selection():
    return {'version': 1, 'roi': [0.02, 0.1, 0.98, 0.65],
            'seeds': [[0.12 + i * .1, .35] for i in range(8)],
            'confirmed_same_boat': True}


def frame(y=35, shift=0):
    boxes = np.array([[x-3+shift,y-8,x+3+shift,y+8] for x in range(12,83,10)],float)
    k = np.ones((8,17,3)); k[:,:,0] = boxes[:,0,None]+3; k[:,:,1]=y
    return boxes,k


class SelectedCrewTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.selection'),
                             'one-boat selection behavior is missing')
        from strokesense import selection as mod
        return mod

    def test_versioned_selection_requires_eight_distinct_same_boat_seeds(self):
        m=self.module(); good=selection()
        self.assertEqual(m.validate_selection(good),good)
        for bad in [dict(good,seeds=good['seeds'][:7]),dict(good,confirmed_same_boat=False),
                    dict(good,roi=[0,0,float('nan'),1]),dict(good,version=2),
                    dict(good,seeds=[good['seeds'][0]]*8),dict(good,unexpected='rule')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):m.validate_selection(bad)

    def test_only_clicked_boat_is_retained_even_when_second_boat_is_larger(self):
        m=self.module(); a,ak=frame(); b,bk=frame(y=82)
        dets=[(np.vstack([b,a]),np.vstack([bk,ak])),
              (np.vstack([b,a+np.array([1,0,1,0])]),np.vstack([bk,ak]))]
        tracks=m.locked_tracks(dets,{'width':100,'height':100},selection())
        self.assertEqual(set(tracks),set(range(8)))
        for i,track in tracks.items():
            np.testing.assert_array_equal(track['frames'],[0,1])
            self.assertTrue(np.all(track['boxes'][:,1]<65))
            self.assertAlmostEqual(track['boxes'][0,0],a[i,0])

    def test_missing_or_ambiguous_initial_targets_never_fall_back_to_other_boat(self):
        m=self.module(); a,k=frame()
        with self.assertRaises(m.SelectionError):m.locked_tracks([(a[:7],k[:7])],{'width':100,'height':100},selection())
        extra=a[0:1]+np.array([.1,0,.1,0])
        with self.assertRaises(m.SelectionError):m.locked_tracks([(np.vstack([a,extra]),np.vstack([k,k[:1]]))],{'width':100,'height':100},selection())

    def test_tracking_loss_fails_closed_instead_of_replacing_a_selected_seat(self):
        m=self.module();a,k=frame();b,bk=frame(y=82)
        with self.assertRaises(m.SelectionError):
            m.locked_tracks([(a,k),(np.vstack([a[:7],b]),np.vstack([k[:7],bk]))],{'width':100,'height':100},selection())

    def test_cache_identity_changes_with_selection_but_legacy_is_compatible(self):
        self.assertIn('selection',inspect.signature(cli._cache_identity).parameters)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'clip.mov';p.write_bytes(b'fixture')
            base=cli._cache_identity(p,0,None,'auto',15,None)
            sel=selection(); other=copy.deepcopy(sel);other['seeds'][0][0]+=.01
            one=cli._cache_identity(p,0,None,'auto',15,None,selection=sel)
            two=cli._cache_identity(p,0,None,'auto',15,None,selection=other)
            self.assertNotEqual(base,one);self.assertNotEqual(one,two)
            self.assertEqual(one,cli._cache_identity(p,0,None,'auto',15,None,selection=sel))

    def test_selection_is_saved_per_job_and_forwarded_unchanged(self):
        self.assertIn('selection',inspect.signature(JobQueue.submit).parameters)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);video=root/'clip.mov';video.write_bytes(b'synthetic')
            db=root/'clips.db';clip,_=register_clip(video,db,permission='granted',provenance='synthetic')
            seen=[]
            def analyze(video,*,out_dir,selection):
                seen.append(selection);return None
            with JobQueue(registry_db=db,job_db=root/'jobs.db',results_root=root/'results',analyze_fn=analyze) as q:
                s=selection();j=q.submit(clip['clip_id'],selection=s);q.wait(j['job_id'],timeout=3)
                self.assertEqual(seen,[s]);self.assertEqual(q.selection(j['job_id']),s)
            with JobQueue(registry_db=db,job_db=root/'jobs.db',results_root=root/'results',analyze_fn=analyze) as q:
                self.assertEqual(q.selection(j['job_id']),s)

    def test_region_is_cropped_before_inference_and_coordinates_restored(self):
        self.assertIn('selection',inspect.signature(pose.run_video).parameters)
        image=np.zeros((100,100,3),np.uint8)
        class Capture:
            def isOpened(self):return True
            def get(self,key):return 15 if key==pose.cv2.CAP_PROP_FPS else 1
            def set(self,*args):pass
            def read(self):return True,image.copy()
            def release(self):pass
        seen=[]
        def detector(fr,tiles=None):
            seen.append(fr.shape)
            return np.array([[1,2,4,5]],float),np.ones(1),np.ones((1,17,3))
        with patch.object(pose.cv2,'VideoCapture',return_value=Capture()):
            dets,meta=pose.run_video('fixture',detector,tiles=None,selection=selection())
        self.assertEqual(seen,[(55,96,3)])
        np.testing.assert_array_equal(dets[0][0],[[3,12,6,15]])

if __name__=='__main__':unittest.main()
