"""Shared cadence behavior with synthetic timing evidence, not accuracy labels."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import cadence


def rower(i, rates=None, *, offset=0., fps=30., intervals=None):
    if intervals is None:
        intervals = []
        start = offset
        for rate in rates or [24.] * 8:
            end = start + 60 / rate
            intervals.append((start, end))
            start = end
    cycles = [SimpleNamespace(catch_t=a*fps, next_catch_t=b*fps,
                              rate=60/(b-a), catch=round(a*fps), next_catch=round(b*fps))
              for a, b in intervals]
    return SimpleNamespace(tid=i, seat=f'R{i+1}', k=SimpleNamespace(fps=fps),
                           strokes=cycles, summary={'rate': cycles[0].rate if cycles else None})


class BoatCadenceTests(unittest.TestCase):
    def test_fixed_phase_offsets_share_one_rate_without_aligned_catches(self):
        people = [rower(i, offset=.27*i) for i in range(8)]
        before = copy.deepcopy([vars(s) for r in people for s in r.strokes])
        result = cadence.estimate(people)
        self.assertAlmostEqual(result['rate_spm'], 24., places=7)
        self.assertEqual(result['supporting_rowers'], 8)
        self.assertEqual(len(result['shared_cycles']), 0)
        self.assertFalse(result['sample_ready'], 'frequency agreement must not invent aligned catches')
        self.assertTrue(all(p['shared_rate_spm'] == result['rate_spm']
                            for p in result['per_rower'].values()))
        self.assertEqual(before, [vars(s) for r in people for s in r.strokes])

    def test_two_observed_cycles_with_phase_offsets_are_sufficient_for_pair(self):
        result = cadence.estimate([rower(0, [24]*2), rower(1, [24]*2, offset=.4)])
        self.assertAlmostEqual(result['rate_spm'], 24.)
        self.assertAlmostEqual(result['support_duration_seconds'], 4.6)
        self.assertEqual(result['supporting_cycles'], 4)

    def test_time_units_do_not_depend_on_analysis_fps(self):
        for fps in (10., 12.5, 30.):
            with self.subTest(fps=fps):
                result = cadence.estimate([rower(i, fps=fps, offset=.13*i) for i in range(4)])
                self.assertAlmostEqual(result['rate_spm'], 24., places=7)

    def test_many_outlier_cycles_still_have_only_one_rower_vote(self):
        people = [rower(i, offset=.05*i) for i in range(4)]
        people.append(rower(4, [48]*16))
        result = cadence.estimate(people)
        self.assertAlmostEqual(result['rate_spm'], 24.)
        self.assertEqual(result['supporting_rowers'], 4)
        self.assertEqual(result['per_rower']['R5']['raw_spm'], 48.)
        self.assertEqual(result['per_rower']['R5']['state'], 'inconsistent_with_crew')
        self.assertEqual(result['per_rower']['R5']['contributing_cycles'], 0)

    def test_single_cycles_never_establish_multi_cycle_support(self):
        result = cadence.estimate([rower(i, [24]) for i in range(8)])
        self.assertIsNone(result['rate_spm'])
        self.assertEqual(result['supporting_rowers'], 0)
        people = [rower(i) for i in range(3)] + [rower(3, [48])]
        result = cadence.estimate(people)
        self.assertEqual(result['supporting_rowers'], 3)
        self.assertEqual(result['per_rower']['R4']['state'], 'insufficient_cycles')

    def test_equal_frequency_groups_are_ambiguous_including_harmonics(self):
        for rates in ((24., 48.), (20., 40.)):
            with self.subTest(rates=rates):
                # Both groups cover exactly the same source-time range.
                people = [rower(i, [rates[i//4]]*(8 if i < 4 else 16)) for i in range(8)]
                result = cadence.estimate(people)
                self.assertIsNone(result['rate_spm'])
                self.assertEqual(result['reason'], 'ambiguous_cadence')
                self.assertIsNone(result['rate_range_spm'])

    def test_one_vote_margin_between_distinct_groups_is_not_enough(self):
        people = [rower(i, [24]*8) for i in range(3)]
        people += [rower(i, [40]*14) for i in range(3, 5)]
        self.assertIsNone(cadence.estimate(people)['rate_spm'])

    def test_individually_stable_but_nonoverlapping_tracks_are_not_consensus(self):
        result = cadence.estimate([rower(i, offset=30*i) for i in range(8)])
        self.assertIsNone(result['rate_spm'])
        self.assertEqual(result['support_duration_seconds'], 0.)

    def test_unobserved_gap_is_never_in_trend_or_support_duration(self):
        spans = [(0., 2.5), (2.5, 5.), (12., 14.5), (14.5, 17.)]
        result = cadence.estimate([rower(i, intervals=spans) for i in range(4)])
        self.assertAlmostEqual(result['rate_spm'], 24.)
        self.assertAlmostEqual(result['support_duration_seconds'], 10.)
        self.assertTrue(all(w['end_seconds'] <= 5. or w['start_seconds'] >= 12.
                            for w in result['trend']))
        self.assertEqual(len(result['interval_evidence']), 16)

    def test_gradual_real_change_is_preserved_in_trend(self):
        rates = list(range(20, 37, 2))
        result = cadence.estimate([rower(i, rates, offset=.04*i) for i in range(8)])
        self.assertIsNotNone(result['rate_spm'])
        self.assertGreater(result['rate_range_spm'][1]-result['rate_range_spm'][0], 10.)
        self.assertLess(result['trend'][0]['rate_spm'], result['trend'][-1]['rate_spm'])
        self.assertEqual(result['supporting_rowers'], 8)

    def test_sustained_pace_change_retains_both_observed_rates(self):
        result = cadence.estimate([rower(i, [24]*6+[36]*8) for i in range(4)])
        self.assertIsNotNone(result['rate_spm'])
        self.assertAlmostEqual(result['rate_range_spm'][0], 24.)
        self.assertAlmostEqual(result['rate_range_spm'][1], 36.)
        self.assertLess(result['trend'][0]['rate_spm'], result['trend'][-1]['rate_spm'])

    def test_duplicate_track_identities_cannot_create_a_quorum(self):
        people = [rower(i) for i in range(3)]
        people[2].tid = people[1].tid
        result = cadence.estimate(people)
        self.assertIsNone(result['rate_spm'])
        self.assertFalse(result['sample_ready'])
        people = [rower(i) for i in range(3)]
        people[2].seat = people[1].seat
        self.assertIsNone(cadence.estimate(people)['rate_spm'])

    def test_repeated_single_interval_is_not_multiple_observations(self):
        people = [rower(i, intervals=[(0., 2.5)]*5) for i in range(4)]
        result = cadence.estimate(people)
        self.assertIsNone(result['rate_spm'])
        self.assertEqual(len(result['interval_evidence']), 4)

    def test_invalid_timing_is_excluded_and_output_is_finite_json(self):
        people = [rower(i) for i in range(4)]
        for r, bad in zip(people, (float('nan'), float('inf'), -1., 0.)):
            r.k.fps = bad
        result = cadence.estimate(people)
        self.assertIsNone(result['rate_spm'])
        json.dumps(result, allow_nan=False)
        people = [rower(i) for i in range(4)]
        for r in people:
            for s in r.strokes:
                s.catch_t = float('nan')
        result = cadence.estimate(people)
        self.assertIsNone(result['rate_spm'])
        json.dumps(result, allow_nan=False)

    def test_aligned_five_cycles_remain_an_independent_readiness_measure(self):
        result = cadence.estimate([rower(i, [30]*5, offset=.01*i) for i in range(4)])
        self.assertAlmostEqual(result['rate_spm'], 30.)
        self.assertEqual(len(result['shared_cycles']), 5)
        self.assertEqual(len(result['five_cycle_windows']), 1)
        self.assertTrue(result['sample_ready'])

    def test_alternating_half_double_intervals_do_not_create_midpoint_rate(self):
        result = cadence.estimate([rower(i, [24, 48]*8) for i in range(4)])
        self.assertIsNone(result['rate_spm'])

    def test_short_clear_tail_does_not_hide_mostly_divided_observations(self):
        people = [rower(i, [24]*12) for i in range(4)]
        people += [rower(i, [48]*20) for i in range(4, 8)]
        result = cadence.estimate(people)
        self.assertIsNone(result['rate_spm'], 'five clear seconds must not hide 25 divided seconds')


if __name__ == '__main__':
    unittest.main()
