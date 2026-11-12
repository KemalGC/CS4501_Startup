"""Contract tests for the opt-in, offline synthetic browser demo.

Never call a live model, load user footage, or assert technique accuracy.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class OfflineBrowserDemoTests(unittest.TestCase):
    def test_demo_traverses_upload_status_report_and_withheld_evidence(self):
        from strokesense.demo import run_demo
        result = run_demo()
        self.assertEqual(result["mode"], "synthetic-offline")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["coaching_state"], "withheld")
        self.assertTrue(result["synthetic_report_observed"])
        self.assertEqual(result["evidence_strokes"], 3)
        self.assertFalse(result["real_video_used"])
        self.assertFalse(result["pose_inference_used"])
        self.assertFalse(result["live_llm_used"])
        self.assertNotIn("/tmp/", json.dumps(result))

    def test_demo_failure_path_never_claims_report_or_advice(self):
        from strokesense.demo import run_demo
        result = run_demo(simulate_failure=True)
        self.assertEqual(result["mode"], "synthetic-offline")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "invalid_media")
        self.assertFalse(result["synthetic_report_observed"])
        self.assertEqual(result["coaching_state"], "withheld")
        self.assertFalse(result["live_llm_used"])

    def test_demo_cli_prints_safe_json_and_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, "-m", "strokesense.demo"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed["status"], "succeeded")
        self.assertEqual(parsed["mode"], "synthetic-offline")
        self.assertNotIn("token", proc.stdout.lower())
        self.assertNotIn("private", proc.stdout.lower())
        self.assertNotIn("/tmp/", proc.stdout)


if __name__ == "__main__":
    unittest.main()
