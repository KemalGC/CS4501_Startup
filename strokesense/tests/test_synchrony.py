"""Crew timing association against known event identities and offsets."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense.synchrony import match_events
from strokesense.crew import crew_sync


def row(tid, events, fps=15):
    return NS(tid=tid,seat=str(tid),k=NS(fps=fps),sync_ms=123,sync_sd_ms=456,
              strokes=[NS(catch_t=a,next_catch_t=b) for a,b in zip(events,events[1:])])


class SynchronyTests(unittest.TestCase):
    def test_known_offsets_and_one_use(self):
        rows=[row(i,np.arange(10,161,30)+offset) for i,offset in enumerate([-1.5,-.5,.5,1.5])]
        result=crew_sync(rows,15)
        self.assertEqual(len(result['matched_events']),6)
        for r,offset in zip(rows,[-1.5,-.5,.5,1.5]):
            self.assertAlmostEqual(r.sync_ms,offset/15*1000)
            self.assertAlmostEqual(r.sync_sd_ms,0)
        seen=[(o['rower'],o['frame']) for g in result['matched_events'] for o in g['observations']]
        self.assertEqual(len(seen),len(set(seen)))

    def test_disconnected_cycle_endpoints_are_preserved(self):
        rows=[row(i,[10,40,100,130]) for i in range(4)]
        for r in rows:r.strokes.pop(1)
        self.assertEqual([g['frame'] for g in match_events(rows,15)],[10,40,100,130])

    def test_evenly_split_crew_does_not_invent_consensus(self):
        rows=[row(i,np.arange(10,161,30)+(0 if i<4 else 15)) for i in range(8)]
        self.assertEqual(match_events(rows,15),[])

    def test_duplicate_identity_or_seat_cannot_vote(self):
        rows=[row(i,[10,40,70]) for i in range(4)]
        rows[1].tid=rows[0].tid
        self.assertEqual(match_events(rows,15),[])
        rows[1].tid=1;rows[1].seat=rows[0].seat
        self.assertEqual(match_events(rows,15),[])

    def test_noisy_extra_catches_do_not_move_consistent_majority(self):
        rows=[row(i,[10,55,100,145]) for i in range(7)]
        rows.append(row(7,[10,32.5,55,77.5,100,122.5,145]))
        result=crew_sync(rows,15)
        self.assertEqual([g['frame'] for g in result['matched_events']],[10,55,100,145])
        for r in rows:self.assertAlmostEqual(r.sync_ms,0)

    def test_clustered_false_reference_catch_does_not_duplicate_other_seats(self):
        rows=[row(i,[10,40,70,100]) for i in range(8)]
        rows[0].strokes=[NS(catch_t=a,next_catch_t=b) for a,b in [(10,40),(14,44),(70,100)]]
        result=crew_sync(rows,15)
        self.assertEqual([g['frame'] for g in result['matched_events']],[10,40,70,100])
        for r in rows[1:]:
            self.assertEqual(result['per_seat'][r.seat]['n'],4)
            self.assertAlmostEqual(r.sync_ms,0)
        for group in result['matched_events'][:2]:
            self.assertNotIn(0,[o['rower'] for o in group['observations']])

    def test_stale_measurements_cleared_when_evidence_disappears(self):
        rows=[row(i,[]) for i in range(4)]
        result=crew_sync(rows,15)
        self.assertEqual(result['per_seat'],{})
        self.assertTrue(all(r.sync_ms is None and r.sync_sd_ms is None for r in rows))
        r=row(0,[]);self.assertEqual(crew_sync([r],15),{});self.assertIsNone(r.sync_ms)

    def test_actual_rate_changes_and_gaps_preserved(self):
        events=[10,60,105,145,180,210,240]
        rows=[row(i,events) for i in range(4)]
        self.assertEqual([g['frame'] for g in match_events(rows,15)],events)

    def test_invalid_clocks_and_nonfinite_catches(self):
        rows=[row(i,[10,40,70]) for i in range(4)]
        for fps in [0,-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):match_events(rows,fps)
        for r in rows:r.k.fps=30
        self.assertEqual(match_events(rows,15),[])
        for r in rows:r.k.fps=15;r.strokes=[NS(catch_t=float('nan'),next_catch_t=40)]
        self.assertEqual(match_events(rows,15),[])

if __name__=='__main__':unittest.main()
