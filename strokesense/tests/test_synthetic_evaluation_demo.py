"""Explicitly synthetic evaluation CLI demonstration; no human review or model run."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "synthetic_opportunities.json"


class SyntheticEvaluationDemoTests(unittest.TestCase):
    def test_example_has_only_fictional_labeled_opportunities(self):
        # Test-first missing artifact assertion, not an environment import failure.
        self.assertTrue(EXAMPLE.is_file(), "The documented synthetic demo data is missing")
        rows = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(
            row["clip_id"].startswith("synthetic-")
            and row["group_id"].startswith("synthetic-")
            and row["stroke_id"].startswith("synthetic-")
            and row["review_status"] == "reviewed"
            for row in rows
        ))
        self.assertEqual({r["split"] for r in rows}, {"development", "heldout"})

    def test_documented_cli_is_reproducible_and_does_not_print_private_ids(self):
        self.assertTrue(EXAMPLE.is_file(), "The documented synthetic demo data is missing")
        args = [sys.executable, "-m", "strokesense.evaluation", str(EXAMPLE)]
        first = subprocess.run(args, cwd=ROOT, capture_output=True,
                               text=True, timeout=15, check=False)
        second = subprocess.run(args, cwd=ROOT, capture_output=True,
                                text=True, timeout=15, check=False)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, second.stdout)
        report = json.loads(first.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["evaluated_opportunities"], 8)
        development = report["by_split"]["development"]
        early = development["early_arms"]
        self.assertEqual(
            (early["tp"], early["fp"], early["fn"], early["tn"]),
            (1, 1, 1, 1),
        )
        self.assertEqual((early["precision"], early["recall"]), (0.5, 0.5))
        other = development["over_compression"]
        self.assertEqual((other["tp"], other["fp"], other["fn"], other["tn"]),
                         (0, 0, 1, 1))
        self.assertIsNone(other["precision"])
        heldout = report["by_split"]["heldout"]["early_arms"]
        self.assertEqual((heldout["tp"], heldout["tn"]), (1, 1))
        for marker in ("synthetic-clip", "synthetic-session", "synthetic-stroke"):
            self.assertNotIn(marker, first.stdout)


if __name__ == "__main__":
    unittest.main()
