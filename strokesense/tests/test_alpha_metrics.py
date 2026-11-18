"""Issue #122: AI-authored acceptance tests committed before implementation.
Human inspection is still required; these are not human validation responses.
"""
import importlib
import unittest

class AlphaMetricsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('strokesense.alpha_metrics')
        except ModuleNotFoundError:
            self.fail('Required alpha_metrics module has not been implemented')

    def test_success_and_distinct_test_count(self):
        log = 'test_a (suite.C.test_a) ... ok\ntest_a (suite.C.test_a) ... ok\ntest_b (suite.C.test_b) ... ok\nRan 3 tests in 0.1s\nOK\n'
        r = self.m.parse_unittest_log(log)
        self.assertEqual((r['executions'], r['unique_tests'], r['repeated_executions']), (3, 2, 1))
        self.assertEqual(r['pass_rate_pct'], 100.0)
        self.assertTrue(r['complete'])

    def test_failure_error_and_skip_are_not_passes(self):
        log = 'test_a (suite.C.test_a) ... FAIL\ntest_b (suite.C.test_b) ... ERROR\ntest_c (suite.C.test_c) ... skipped\ntest_d (suite.C.test_d) ... ok\nRan 4 tests in 0.1s\nFAILED (failures=1, errors=1, skipped=1)\n'
        r = self.m.parse_unittest_log(log)
        self.assertEqual((r['passed'], r['failures'], r['errors'], r['skipped']), (1, 1, 1, 1))
        self.assertEqual(r['pass_rate_pct'], 25.0)

    def test_empty_log_does_not_claim_success(self):
        r = self.m.parse_unittest_log('')
        self.assertFalse(r['complete'])
        self.assertIsNone(r['pass_rate_pct'])

    def test_zero_tests_has_no_pass_rate(self):
        r = self.m.parse_unittest_log('Ran 0 tests in 0.000s\nOK\n')
        self.assertIsNone(r['pass_rate_pct'])
        self.assertEqual(r['executions'], 0)

    def test_interrupted_log_is_incomplete(self):
        r = self.m.parse_unittest_log('test_a (suite.C.test_a) ... ok\n')
        self.assertFalse(r['complete'])
        self.assertIsNone(r['pass_rate_pct'])

    def test_mismatched_run_and_source_rejected(self):
        with self.assertRaises(ValueError):
            self.m.assert_same_commit('a'*40, 'b'*40)

    def test_same_commit_is_accepted(self):
        self.assertIsNone(self.m.assert_same_commit('a'*40, 'a'*40))

    def test_line_coverage_is_not_combined_coverage(self):
        r = self.m.coverage_metrics({'totals': {'covered_lines': 8, 'num_statements': 10, 'percent_covered': 66.0, 'covered_branches': 2, 'num_branches': 5}})
        self.assertEqual(r['line_coverage_pct'], 80.0)
        self.assertEqual(r['branch_coverage_pct'], 40.0)

    def test_zero_line_denominator_is_unknown(self):
        r = self.m.coverage_metrics({'totals': {'covered_lines': 0, 'num_statements': 0}})
        self.assertIsNone(r['line_coverage_pct'])

    def test_invalid_coverage_counts_rejected(self):
        with self.assertRaises(ValueError):
            self.m.coverage_metrics({'totals': {'covered_lines': 11, 'num_statements': 10}})

    def test_mapping_uses_explicit_denominator(self):
        r = self.m.issue_metrics({'10': ['a', 'b'], '11': ['b']}, ['a', 'b'], [10])
        self.assertEqual((r['issues'], r['closed_issues'], r['test_issue_links'], r['unique_mapped_tests']), (2, 1, 3, 2))
        self.assertEqual(r['average_tests_per_issue'], 1.5)

    def test_mapping_rejects_nonexistent_tests(self):
        with self.assertRaises(ValueError):
            self.m.issue_metrics({'10': ['unknown']}, ['a'], [])

    def test_empty_mapping_is_not_zero_average(self):
        r = self.m.issue_metrics({}, [], [])
        self.assertIsNone(r['average_tests_per_issue'])

    def test_provenance_unknown_is_not_manual(self):
        r = self.m.test_provenance(['a', 'b', 'c'], {'a': 'ai_generated', 'b': 'human_refined_or_added'})
        self.assertEqual((r['ai_generated'], r['human_refined_or_added'], r['unknown']), (1, 1, 1))
        self.assertIsNone(r['overall_ai_pct'])

    def test_provenance_deduplicates_executions(self):
        r = self.m.test_provenance(['a', 'a'], {'a': 'ai_generated'})
        self.assertEqual((r['total'], r['ai_generated'], r['overall_ai_pct']), (1, 1, 100.0))

    def test_provenance_rejects_unsupported_attribution(self):
        with self.assertRaises(ValueError):
            self.m.test_provenance(['a'], {'a': 'probably_ai'})

if __name__ == '__main__':
    unittest.main()
