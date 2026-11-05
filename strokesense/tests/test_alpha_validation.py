"""Synthetic contract tests, NOT measured human validation results."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.alpha_validation import summarize, load_pilot_csv

def row(pid, **updates):
    base = dict(participant_id=pid, consent='yes', coached_before='no',
        baseline_seconds='', assisted_seconds='', timing_method='',
        detail_preserved='', actionable='', comment='', withdrawn='no')
    base.update(updates)
    return base

class AlphaValidationTests(unittest.TestCase):
    def test_empty_template_cannot_claim_hypothesis(self):
        a=summarize([row(f'R{i:02}',consent='',coached_before='') for i in range(1,8)])
        self.assertEqual(a['declared_sample_n'],7)
        self.assertEqual(a['consented_n'],0)
        self.assertIsNone(a['median_review_time_reduction_pct'])
        self.assertEqual(a['decision'],'NOT_YET_VALIDATED')
    def test_two_with_prior_coaching_not_two_independent_coaches(self):
        rows=[row(f'R{i:02}',coached_before='yes' if i in (1,2) else 'no') for i in range(1,8)]
        a=summarize(rows)
        self.assertEqual(a['profile_prior_coaching_yes_n'],2)
        self.assertIsNone(a['expert_agreement_pct'])
        self.assertIsNone(a['qualified_coach_actionability_pct'])
    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            summarize([row('R01'),row('R01')])
    def test_invalid_id_rejected(self):
        with self.assertRaises(ValueError): summarize([row('../secret')])
    def test_negative_time_rejected(self):
        with self.assertRaises(ValueError):
            summarize([row('R01', baseline_seconds='-5',assisted_seconds='1',timing_method='stopwatch')])
    def test_missing_time_cannot_be_imputed(self):
        a=summarize([row('R01',baseline_seconds='50',timing_method='stopwatch')])
        self.assertEqual(a['timed_pairs_n'],0)
    def test_estimated_time_is_not_measured(self):
        a=summarize([row('R01',baseline_seconds='100',assisted_seconds='50',timing_method='estimate')])
        self.assertEqual(a['timed_pairs_n'],0)
        self.assertIsNone(a['median_review_time_reduction_pct'])
    def test_median_of_two_workflows_not_average_of_percentages(self):
        a=summarize([row('R01',baseline_seconds='100',assisted_seconds='70',timing_method='stopwatch'),
                    row('R02',baseline_seconds='200',assisted_seconds='180',timing_method='stopwatch')])
        self.assertEqual(a['timed_pairs_n'],2)
        self.assertAlmostEqual(a['median_review_time_reduction_pct'], round(100*(150-125)/150,2))
    def test_preserved_and_actionable_have_explicit_denominators(self):
        a=summarize([row('R01',detail_preserved='yes',actionable='yes'),
                    row('R02',detail_preserved='no',actionable=''),
                    row('R03',detail_preserved='',actionable='no')])
        self.assertEqual(a['detail_preserved'],{'yes_n':1,'responded_n':2,'pct':50.0})
        self.assertEqual(a['actionable'],{'yes_n':1,'responded_n':2,'pct':50.0})
    def test_withdrawn_data_excluded_from_metrics(self):
        a=summarize([row('R01',withdrawn='yes',baseline_seconds='10',assisted_seconds='1',timing_method='stopwatch')])
        self.assertEqual(a['consented_n'],0)
        self.assertEqual(a['timed_pairs_n'],0)
    def test_consent_is_required_for_metrics(self):
        a=summarize([row('R01',consent='no',detail_preserved='yes')])
        self.assertEqual(a['detail_preserved']['responded_n'],0)
    def test_more_than_seven_rows_rejected(self):
        with self.assertRaises(ValueError):summarize([row(f'R{i:02}') for i in range(1,9)])
    def test_missing_qualified_coach_labels_never_claims_validated(self):
        a=summarize([row(f'R{i:02}',baseline_seconds='100',assisted_seconds='45',timing_method='stopwatch',
                         detail_preserved='yes',actionable='yes') for i in range(1,8)])
        self.assertGreater(a['median_review_time_reduction_pct'],30)
        self.assertEqual(a['decision'],'NOT_YET_VALIDATED')
    def test_unexpected_field_rejected(self):
        with self.assertRaises(ValueError):summarize([dict(row('R01'),secret='bad')])

if __name__=='__main__':unittest.main()
