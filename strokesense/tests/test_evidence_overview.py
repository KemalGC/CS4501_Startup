"""Tests-first local evidence overview UI contract (#91).

Uses the existing synthetic verified snapshot fixture. No athlete footage,
reviewed fault labels, provider calls, or model inference are used.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_ui import EvidenceInterfaceTests


class EvidenceOverviewTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing isolated, real HTTP test server and integrity-checked
        # synthetic JobQueue fixture, without inheriting its unrelated tests.
        self.rig = EvidenceInterfaceTests(
            methodName="test_human_readable_evidence_links_to_strokes_and_times"
        )
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def page(self, *, fault=""):
        job_id = self.rig.succeed()
        route = f"/jobs/{job_id}/evidence"
        if fault:
            route += f"?fault={fault}"
        status, headers, data = self.rig.request(route)
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(str(self.rig.root).encode(), data)
        return job_id, data.decode("utf-8")

    def test_saved_snapshot_counts_and_navigation_are_accessible(self):
        _, page = self.page()
        self.assertIn(
            '<section class="evidence-workspace" aria-labelledby="evidence-summary-title">',
            page,
        )
        self.assertIn('<h2 id="evidence-summary-title">Saved evidence overview</h2>', page)
        self.assertIn('<dl class="evidence-stats">', page)
        for label, count in (("Seats", 1), ("Saved strokes", 3),
                             ("Candidate findings", 1)):
            with self.subTest(label=label):
                self.assertIn(f"<dt>{label}</dt><dd>{count}</dd>", page)
        self.assertIn('<nav class="evidence-jump" aria-label="Jump to evidence details">', page)
        for target in ("seats", "strokes", "findings"):
            self.assertIn(f'href="#evidence-{target}"', page)
            self.assertIn(f'<section id="evidence-{target}"', page)
        self.assertIn("Generated coaching withheld", page)
        self.assertIn("not coach-reviewed", page)
        self.assertIn("@media (max-width: 720px)", page)
        self.assertIn(".evidence-stats", page)
        self.assertIn(":focus-visible", page)
        self.assertNotIn("<script", page)
        self.assertNotIn('<link rel="stylesheet"', page)

    def test_fault_filter_retains_full_snapshot_totals_and_evidence_links(self):
        job_id, page = self.page(fault="early_arms")
        self.assertIn("Totals describe the full saved snapshot", page)
        self.assertIn("<dt>Seats</dt><dd>1</dd>", page)
        self.assertIn("<dt>Saved strokes</dt><dd>3</dd>", page)
        self.assertIn("<dt>Candidate findings</dt><dd>1</dd>", page)
        self.assertIn("Showing candidate fault:", page)
        self.assertIn(f'href="/jobs/{job_id}/evidence"', page)
        self.assertIn('id="stroke-0"', page)
        self.assertNotIn('id="stroke-1"', page)
        self.assertIn('href="#stroke-0"', page)
        # Existing public API remains structured evidence, not the HTML cards.
        status, headers, payload = self.rig.request(f"/api/jobs/{job_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(len(json.loads(payload)["evidence"]["strokes"]), 3)
        self.assertNotIn(b"evidence-workspace", payload)

    def test_zero_candidate_findings_show_a_truthful_empty_state(self):
        import copy
        from strokesense.evidence import _digest, validate_public_evidence_snapshot

        self.rig.snapshot = copy.deepcopy(self.rig.snapshot)
        self.rig.snapshot["findings"] = []
        for stroke in self.rig.snapshot["strokes"]:
            stroke["fault_codes"] = []
        self.rig.snapshot["snapshot_sha256"] = _digest({
            key: value for key, value in self.rig.snapshot.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(validate_public_evidence_snapshot(self.rig.snapshot))
        _, page = self.page()
        self.assertIn("<dt>Candidate findings</dt><dd>0</dd>", page)
        self.assertIn("No candidate findings in this saved snapshot.", page)
        self.assertNotIn("0% accurate", page)


if __name__ == "__main__":
    unittest.main()
