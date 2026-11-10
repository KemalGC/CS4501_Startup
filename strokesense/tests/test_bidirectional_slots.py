"""Regression tests for missing leading observations and duplicate anchors."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.pose import crew_tracks
from test_dominant_crew import boxes as raw_boxes

def boxes():
    b, k = raw_boxes()
    k[:, :, :2] = ((b[:, :2] + b[:, 2:]) / 2)[:, None, :]
    k[:, [13, 14], 0] += 6
    return b, k

class BidirectionalSlotsTests(unittest.TestCase):
    def test_partial_leading_frames_are_recovered_without_inventing_missing_seat(self):
        b,k=boxes()
        frames=[(b[:7].copy(),k[:7].copy()) for _ in range(8)]
        frames += [(b.copy(),k.copy()) for _ in range(24)]
        tracks,_,count=crew_tracks(frames,10)
        self.assertEqual(count,8)
        self.assertEqual(len(tracks),8)
        for i in range(7):
            np.testing.assert_array_equal(tracks[i]['frames'],np.arange(32))
        np.testing.assert_array_equal(tracks[7]['frames'],np.arange(8,32))

    def test_empty_frames_are_never_observed(self):
        b,k=boxes();empty=(np.zeros((0,4)),np.zeros((0,17,3)))
        frames=[(b.copy(),k.copy()) for _ in range(10)]+[empty]*3+[(b.copy(),k.copy()) for _ in range(10)]
        tracks,_,_=crew_tracks(frames,10)
        for t in tracks.values():
            self.assertEqual(len(t['frames']),20)
            self.assertFalse(set(range(10,13)) & set(t['frames']))

    def test_missing_middle_seat_does_not_shift_neighbours(self):
        b,k=boxes()
        frames=[(b.copy(),k.copy()) for _ in range(10)]
        ids=[0,1,2,4,5,6,7]
        frames += [(b[ids].copy(),k[ids].copy()) for _ in range(5)]
        frames += [(b.copy(),k.copy()) for _ in range(10)]
        tracks,_,_=crew_tracks(frames,10,expected_seats=8)
        for seat,t in tracks.items():
            np.testing.assert_allclose(t['boxes'],np.tile(b[seat],(len(t['frames']),1)))
        self.assertFalse(set(range(10,15)) & set(tracks[3]['frames']))

    def test_declared_size_does_not_pad_seven_detections(self):
        b,k=boxes()
        tracks,_,_=crew_tracks([(b[:7],k[:7])]*20,10,expected_seats=8)
        self.assertEqual(tracks,{})

if __name__=='__main__':unittest.main()
