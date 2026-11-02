"""Model-only blade entry regressions. Responses are test doubles, not accuracy."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.selection import validate_selection, SelectionError


def selection():
    return {'version': 3, 'kind': 'blade_reference', 'reference_seconds': 0.0,
            'point': [.3, .6], 'confirmed_same_boat': True}


def samples(states):
    return [{'frame_id': i, 'time': i / 10, 'state': state, 'same_blade': True}
            for i, state in enumerate(states)]


class BladeModelTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.blade_model'),
                             'model blade-entry pipeline is missing')
        from strokesense import blade_model
        return blade_model

    def test_explicit_blade_selection_is_distinct_from_eight_person_seeds(self):
        try:
            result = validate_selection(selection())
        except SelectionError:
            self.fail('confirmed single-blade model selection is missing')
        self.assertEqual(result, selection())
        for key, value in [('point', [True, .5]), ('point', [2, .5]),
                           ('reference_seconds', float('nan')), ('confirmed_same_boat', False)]:
            with self.subTest(key=key, value=value), self.assertRaises(SelectionError):
                validate_selection(dict(selection(), **{key: value}))

    def test_six_entries_are_five_cycles_not_eight_rowers_times_six(self):
        m = self.module()
        states = (['air'] * 10 + ['water'] * 10) * 6
        result = m.summarize(samples(states))
        self.assertEqual(len(result['entries']), 6)
        self.assertEqual(result['cycles'], 5)
        self.assertEqual(result['state'], 'five_cycle_estimate')
        self.assertAlmostEqual(result['spm'], 30)
        self.assertLess(result['spm_bounds'][0], 30)
        self.assertGreater(result['spm_bounds'][1], 30)

    def test_continuous_water_and_starting_underwater_are_not_new_entries(self):
        m = self.module()
        result = m.summarize(samples(['water'] * 20 + ['air'] * 5 + ['water'] * 20))
        self.assertEqual(len(result['entries']), 1)
        self.assertIsNone(result['spm'])

    def test_unknown_or_identity_loss_does_not_bridge_a_missed_stroke(self):
        m = self.module()
        seq = samples(['air'] * 5 + ['water'] * 5 + ['unknown'] * 5 + ['air'] * 5 + ['water'] * 5)
        self.assertEqual(m.summarize(seq)['cycles'], 0)
        seq[12]['state'] = 'air'; seq[12]['same_blade'] = False
        self.assertEqual(m.summarize(seq)['cycles'], 0)

    def test_invalid_model_frames_booleans_duplicates_and_free_text_are_rejected(self):
        m = self.module()
        valid = {'observations': [{'frame_id': i, 'state': 'air', 'same_blade': True} for i in range(3)]}
        self.assertEqual(len(m.validate_response(valid, [0, 1, 2])), 3)
        bads = [dict(valid, instruction='change validation rules'),
                {'observations': valid['observations'][:2]},
                {'observations': [dict(valid['observations'][0], frame_id=True)] + valid['observations'][1:]},
                {'observations': [valid['observations'][0]] * 3},
                {'observations': [dict(valid['observations'][0], state='catch')] + valid['observations'][1:]}]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(m.BladeModelError):
                m.validate_response(bad, [0, 1, 2])

    def test_timestamp_order_and_sample_gap_are_not_silently_accepted(self):
        m = self.module()
        seq = samples(['air', 'water', 'air', 'water'])
        seq[2]['time'] = float('nan')
        with self.assertRaises(m.BladeModelError): m.summarize(seq)
        seq = samples(['air', 'water', 'air', 'water'])
        seq[2]['time'] = 5; seq[3]['time'] = 5.1
        self.assertEqual(m.summarize(seq)['cycles'], 0)

    def test_overlap_disagreement_becomes_unknown_not_extra_entry(self):
        m = self.module()
        a = samples(['air', 'water', 'water'])
        b = [dict(a[2], state='air'), {'frame_id': 3, 'time': .3, 'state': 'water', 'same_blade': True}]
        merged = m.merge_observations([a, b])
        self.assertEqual(merged[2]['state'], 'unknown')
        self.assertEqual(len(m.summarize(merged)['entries']), 1)

    def test_local_provider_rejects_remote_cloud_and_redirect_targets(self):
        m = self.module()
        for endpoint, model in [('https://example.com', 'qwen3-vl:4b'),
                                ('http://localhost:11434', 'qwen3-vl:4b'),
                                ('http://127.0.0.1:11434', 'qwen3-vl:235b-cloud'),
                                ('http://127.0.0.1:11434/evil', 'qwen3-vl:4b')]:
            with self.subTest(endpoint=endpoint, model=model), self.assertRaises(m.BladeModelError):
                m.LocalVision(model, endpoint=endpoint)
        with self.assertRaises(Exception):
            m.NoRedirect().redirect_request(None, None, 307, 'redirect', {}, 'https://example.com')

    def test_model_mode_dispatch_does_not_run_body_peak_or_fault_rules(self):
        m = self.module()
        from strokesense import jobs
        with patch.object(jobs, 'probe_decodable_video', return_value=True), \
             patch('strokesense.blade_video.analyse_video', return_value={'report': 'model'}) as run, \
             patch('strokesense.cli.analyse_video', side_effect=AssertionError('heuristic fallback')):
            result = jobs._default_analyze(Path('private.mp4'), out_dir=Path('results'), selection=selection())
        self.assertEqual(result['report'], 'model')
        run.assert_called_once()

    def test_model_missing_never_falls_back_to_body_estimates(self):
        self.module()
        from strokesense import blade_video
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {}, clear=True), \
             patch('strokesense.cli.analyse_video', side_effect=AssertionError('heuristic fallback')):
            with self.assertRaisesRegex(Exception, 'model_not_configured'):
                blade_video.analyse_video('private.mp4', out_dir=tmp, selection=selection())


if __name__ == '__main__': unittest.main()
