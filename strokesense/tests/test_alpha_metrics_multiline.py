"""Issue #122 regressions found by inspecting real unittest logs; AI-authored."""
import unittest
from strokesense.alpha_metrics import parse_unittest_log

class MultilineMetricsTests(unittest.TestCase):
    def test_docstring_on_next_line_does_not_drop_test_id(self):
        log = ('test_a (suite.C.test_a)\nA readable description ... ok\n'
               'test_b (suite.C.test_b) ... ok\nRan 2 tests in 0.1s\nOK\n')
        result = parse_unittest_log(log)
        self.assertEqual(result['unique_tests'], 2)
        self.assertEqual(result['repeated_executions'], 0)
        self.assertTrue(result['identity_listing_complete'])

    def test_quiet_log_does_not_invent_unique_test_count(self):
        result = parse_unittest_log('..\nRan 2 tests in 0.1s\nOK\n')
        self.assertEqual(result['executions'], 2)
        self.assertIsNone(result['unique_tests'])
        self.assertFalse(result['identity_listing_complete'])
