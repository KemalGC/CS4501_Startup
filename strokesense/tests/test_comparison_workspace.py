"""Tests-first comparison workspace UI contract (#92).

Real local HTTP and saved synthetic evidence; no actual video or model inference.
The existing fixture class is instantiated, never inherited as a test class.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_evidence_ui as _evidence_fixture
from strokesense import evidence
from strokesense.registry import revoke_clip


class ComparisonWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.rig = _evidence_fixture.EvidenceInterfaceTests(
            methodName="test_human_readable_evidence_links_to_strokes_and_times"
        )
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def pair(self):
        first, last = self.rig.succeed(), self.rig.succeed()
        query = urlencode({"before": first, "after": last})
        return first, last, query

    def test_side_by_side_run_cards_preserve_integrity_gated_actions(self):
        first, last, query = self.pair()
        status, headers, body = self.rig.request("/compare?" + query)
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        page = body.decode("utf-8")
        self.assertIn('<section class="comparison-panel" aria-labelledby="comparison-panel-heading">', page)
        self.assertEqual(page.count('<article class="comparison-run"'), 2)
        self.assertIn("<h3>Earlier run</h3>", page)
        self.assertIn("<h3>Later run</h3>", page)
        for job in (first, last):
            self.assertIn(f'href="/reports/{job}"', page)
            self.assertIn(f'href="/jobs/{job}/evidence"', page)
        self.assertIn("Same registered source clip", page)
        self.assertIn("Coaching withheld", page)
        self.assertIn("not proof of improvement", page)
        self.assertNotIn(str(self.rig.root), page)
        self.assertNotIn("test-only operator claim", page)

    def test_comparison_has_accessible_scrollable_fault_table_and_links(self):
        first, last, query = self.pair()
        status, _, body = self.rig.request("/compare?" + query)
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn('<section class="comparison-findings" aria-labelledby="comparison-findings-heading">', page)
        self.assertIn('<div class="comparison-scroll" role="region" aria-label="Candidate fault comparison table" tabindex="0">', page)
        self.assertIn('<caption>Observed candidate faults across saved analyzed strokes</caption>', page)
        self.assertEqual(page.count('scope="col"'), 3)
        self.assertIn("1 of 3 analyzed strokes", page)
        for job in (first, last):
            self.assertIn(f'href="/jobs/{job}/evidence?fault=early_arms"', page)
        self.assertNotIn("confidence: 100%", page)

    def test_empty_fault_comparison_shows_honest_state_and_no_fault_links(self):
        self.rig.snapshot["findings"] = []
        for stroke in self.rig.snapshot["strokes"]:
            stroke["fault_codes"] = []
        self.rig.snapshot["snapshot_sha256"] = evidence._digest({
            key: value for key, value in self.rig.snapshot.items()
            if key != "snapshot_sha256"
        })
        self.assertTrue(evidence.validate_public_evidence_snapshot(self.rig.snapshot))
        _, _, query = self.pair()
        status, _, body = self.rig.request("/compare?" + query)
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn('class="comparison-empty"', page)
        self.assertIn("not a negative coach-reviewed label", page)
        self.assertNotIn("/evidence?fault=", page)
        self.assertNotIn('class="comparison-table"', page)

    def test_csv_schema_and_permission_gate_remain_unchanged(self):
        first, last, query = self.pair()
        status, headers, body = self.rig.request("/compare.csv?" + query)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(
            body.decode().splitlines()[0],
            "fault_code,before_job_id,before_flagged,before_analyzed,"
            "after_job_id,after_flagged,after_analyzed",
        )
        self.assertIn(first.encode(), body)
        self.assertIn(last.encode(), body)
        revoke_clip(self.rig.clip_id, self.rig.registry)
        denied, _, page = self.rig.request("/compare?" + query)
        self.assertEqual(denied, 403)
        self.assertNotIn(str(self.rig.root).encode(), page)

    def test_invalid_job_ids_are_rejected(self):
        _, last, _ = self.pair()
        status, _, body = self.rig.request("/compare?before=%3Cscript%3E&after=" + last)
        self.assertEqual(status, 400)
        self.assertNotIn(b"test-only operator claim", body)


if __name__ == "__main__":
    unittest.main()
