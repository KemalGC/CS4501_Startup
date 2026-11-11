"""Dashboard identifies generated coaching separately from measured flags."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.hosted_dashboard import build_dashboard


class CoachingSourceTests(unittest.TestCase):
    def test_measured_flags_do_not_claim_generated_coaching(self):
        metrics = {
            "rowers": [
                {"seat": "R1", "strokes": [{} for _ in range(4)], "summary": {
                    "n_strokes": 4,
                    "issues": [{"title": "Rushing the slide", "frac": 0.5}],
                }},
                {"seat": "R2", "strokes": [], "summary": {"n_strokes": 0, "issues": []}},
            ],
        }
        dashboard = self._dashboard(metrics)
        self.assertEqual(dashboard["rowers"][0]["flags"], [
            {"label": "Rushing the slide", "percentage": 50},
        ])
        self.assertEqual(dashboard["rowers"][0]["coaching"], {
            "finding": None, "action": None, "source": "not_generated",
        })
        self.assertEqual(dashboard["rowers"][1]["coaching"]["source"], "not_generated")

    def test_verified_llm_feedback_keeps_generated_provenance(self):
        metrics = {"rowers": [
            {"seat": "R1", "strokes": [{}, {}, {}], "summary": {
                "n_strokes": 3,
                "issues": [{"title": "Opening the back too early", "frac": 1 / 3}],
            }},
            {"seat": "R2", "strokes": [], "summary": {"n_strokes": 0}},
        ]}
        feedback = {"rowers": {"R1": {
            "observation": "The back opens before the legs finish driving.",
            "cue": "Keep the shoulders quiet through the first half of the drive.",
        }}}
        with patch("strokesense.hosted_dashboard._verified_feedback", return_value=feedback):
            dashboard = self._dashboard(metrics)
        coaching = dashboard["rowers"][0]["coaching"]
        self.assertEqual(coaching["source"], "verified_llm")
        self.assertIn("back opens", coaching["finding"])
        self.assertIn("shoulders", coaching["action"])
        self.assertEqual(dashboard["rowers"][0]["flags"][0]["label"],
                         "Opening the back too early")

    def _dashboard(self, metrics):
        metrics["crew_cadence"] = {"rate_spm": None}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.html"
            report.write_text("<main>Fixture</main>", encoding="utf-8")
            (root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
            state = SimpleNamespace(
                snapshot=lambda: {"state": "finished"}, report=report,
                output_root=root, run_id="a" * 32, last_end=None,
            )
            return build_dashboard(state, "Synthetic fixture")


if __name__ == "__main__":
    unittest.main()
