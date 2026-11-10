"""Core association regressions with known physical identities."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.rowing_tracker import SeatTracker, ordered_assignment
from strokesense.pose import clean_detections


def observations(xs=None, shift=(0, 0), scale=1.):
    xs = np.arange(8) * 40. + 40 if xs is None else np.asarray(xs, float)
    b = np.array([[x-12, 40, x+20, 100] for x in xs]) * scale
    k = np.zeros((len(b), 17, 3)); k[..., 2] = .9
    for i, x in enumerate(xs):
        k[i, :, :2] = [x, 65]
        k[i, [5, 6], 1] = 55
        k[i, [11, 12], 1] = 80
        k[i, [13, 14], 0] += 8
    k[..., :2] *= scale
    b += np.tile(shift, 2); k[..., :2] += shift
    return b, k


class RowingTrackerTests(unittest.TestCase):
    def test_camera_jolt_larger_than_old_gate_preserves_ids(self):
        b,k=observations(); tr=SeatTracker(b,k,15)
        b,k=observations(shift=(24,12))
        self.assertEqual(tr.update(b,k),list(enumerate(range(8))))

    def test_zoom_and_perspective_with_missing_middle_and_clutter(self):
        xs=np.array([30,85,135,180,220,255,285,310])
        b,k=observations(xs);tr=SeatTracker(b,k,15)
        for f in range(1,90):
            b,k=observations(xs,shift=(f*1.3, f*.1),scale=1+f*.004)
            ids=[i for i in range(8) if not (i==3 and 10<f<30)]
            clutter,ck=observations([100],shift=(0,200))
            bb=np.concatenate([b[ids],clutter]);kk=np.concatenate([k[ids],ck])
            permutation=np.random.default_rng(f).permutation(len(bb))
            pairs=tr.update(bb[permutation],kk[permutation])
            physical=np.array(ids+[-1])[permutation]
            self.assertEqual({i for i,j in pairs},set(ids))
            self.assertTrue(all(i==physical[j] for i,j in pairs))

    def test_returning_end_seat_requires_continuing_crew_support(self):
        b,k=observations();tr=SeatTracker(b,k,15)
        for _ in range(30):tr.update(b[:-1],k[:-1])
        self.assertEqual(tr.update(b,k),list(enumerate(range(8))))
        empty_b=np.zeros((0,4));empty_k=np.zeros((0,17,3))
        for _ in range(20):self.assertEqual(tr.update(empty_b,empty_k),[])
        self.assertEqual(tr.update(b,k),[])

    def test_equal_competing_observations_are_unavailable(self):
        b,k=observations();tr=SeatTracker(b,k,15)
        b=np.concatenate([b,b[3:4]]);k=np.concatenate([k,k[3:4]])
        pairs=tr.update(b,k)
        self.assertNotIn(3,[i for i,j in pairs])
        self.assertEqual(len(pairs),7)

    def test_gated_assignment_can_skip_both_clutter_and_missing(self):
        cost=np.array([[.1,np.inf,np.inf],[np.inf,np.inf,np.inf],[np.inf,np.inf,.1]])
        self.assertEqual(ordered_assignment(cost)[0],[(0,0),(2,2)])

    def test_distinct_overlapping_torsos_survive_cleanup(self):
        b,k=observations([40,65]);b[:]=[[10,20,100,110],[20,20,110,110]]
        self.assertEqual(len(clean_detections(b,k)[0]),2)

    def test_one_sided_crop_duplicate_is_suppressed(self):
        b,k=observations([40]);small=k.copy();small[:,:,2]=.05
        small[:,[5,11],2]=.9
        # Enough arm confidence to pass the observation gate.
        small[:,[7,9],2]=.9
        bb=np.concatenate([b,[[38,40,50,100]]]);kk=np.concatenate([k,small])
        self.assertEqual(len(clean_detections(bb,kk)[0]),1)

if __name__=='__main__':unittest.main()
