"""Test-first contract for an opt-in *synthetic* coaching correction demo.

No user recordings, provider traffic, human approvals or performance metrics.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class OfflineCoachingDemoTests(unittest.TestCase):
    def test_corrects_and_withholds_without_browser_publication(self):
        from strokesense.demo import run_demo
        with patch("strokesense.provider.urlopen") as external_provider:
            result = run_demo(verify_coaching=True)
        external_provider.assert_not_called()
        self.assertEqual(result["mode"], "synthetic-offline")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["coaching_state"], "withheld")
        self.assertTrue(result["synthetic_report_observed"])
        coaching = result["coaching_validation"]
        self.assertEqual(coaching["mode"], "synthetic-offline-coaching-validation")
        self.assertEqual(coaching["corrected_status"], "released")
        self.assertEqual(coaching["corrected_attempts"], 2)
        self.assertEqual(coaching["rejected_status"], "withheld")
        self.assertEqual(coaching["rejected_attempts"], 3)
        self.assertFalse(coaching["published"])
        self.assertTrue(coaching["fictional_review"])
        self.assertFalse(coaching["live_llm_used"])
        self.assertFalse(result["real_video_used"])
        self.assertFalse(result["pose_inference_used"])
        public = json.dumps(result)
        self.assertNotIn("explanation", public)
        self.assertNotIn("reviewed_by", public)
        self.assertNotIn("private", public.lower())

    def test_failed_job_cannot_claim_coaching_validation(self):
        from strokesense.demo import run_demo
        result = run_demo(simulate_failure=True, verify_coaching=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["coaching_state"], "withheld")
        self.assertFalse(result["synthetic_report_observed"])
        self.assertIsNone(result["coaching_validation"])

    def test_existing_demo_stays_default_and_cli_requires_explicit_flag(self):
        from strokesense.demo import run_demo
        self.assertNotIn("coaching_validation", run_demo())
        completed = subprocess.run(
            [sys.executable, "-m", "strokesense.demo", "--verify-coaching"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-400:])
        parsed = json.loads(completed.stdout)
        self.assertEqual(parsed["coaching_validation"]["corrected_attempts"], 2)
        self.assertEqual(parsed["coaching_validation"]["rejected_attempts"], 3)
        self.assertFalse(parsed["coaching_validation"]["published"])
        self.assertNotIn("synthetic test-only explanation", completed.stdout.lower())
        self.assertNotIn("/tmp/", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
