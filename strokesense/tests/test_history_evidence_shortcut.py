"""Test-first recent-history evidence shortcuts and accessible result cards (#85).

All jobs, bytes, permissions and measurements are synthetic local fixtures.
No inference, athlete recordings, reviewed labels or live LLM calls.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_evidence_ui
from strokesense.registry import revoke_clip


class HistoryEvidenceShortcutTests(unittest.TestCase):
    def setUp(self):
        self.rig = test_evidence_ui.EvidenceInterfaceTests(
            methodName="test_human_readable_evidence_links_to_strokes_and_times"
        )
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def home(self, query=""):
        code, headers, payload = self.rig.request("/" + query)
        self.assertEqual(code, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(str(self.rig.root).encode(), payload)
        self.assertNotIn(b"test-only operator claim", payload)
        return payload.decode("utf-8")

    @staticmethod
    def shortcut(job_id):
        return f'<a href="/jobs/{job_id}/evidence">Inspect saved evidence</a>'

    def test_completed_snapshot_has_prominent_direct_link_and_responsive_cards(self):
        job_id = self.rig.succeed()
        html = self.home()
        self.assertIn(self.shortcut(job_id), html)
        self.assertIn(f'href="/jobs/{job_id}"', html)
        self.assertIn(f'href="/reports/{job_id}"', html)
        self.assertIn('<li class="history-card">', html)
        self.assertIn('class="history-actions"', html)
        self.assertIn(".history-card", html)
        self.assertIn(".history-actions", html)
        self.assertIn("@media (max-width: 720px)", html)
        self.assertIn(":focus-visible", html)
        code, _, evidence = self.rig.request(f"/jobs/{job_id}/evidence")
        self.assertEqual(code, 200)
        self.assertIn(b"Saved evidence overview", evidence)

    def test_filtering_preserves_available_shortcut_but_not_unmatched_rows(self):
        with sqlite3.connect(self.rig.registry) as db:
            db.execute("UPDATE clips SET camera='side-on' WHERE clip_id=?",
                       (self.rig.clip_id,))
        job_id = self.rig.succeed()
        visible = self.home(
            f"?camera=side-on&status=succeeded&clip={self.rig.clip_id}"
        )
        self.assertIn(self.shortcut(job_id), visible)
        for query in ("?status=failed", "?camera=bow-on"):
            with self.subTest(query=query):
                self.assertNotIn(self.shortcut(job_id), self.home(query))

    def test_failed_legacy_and_revoked_jobs_never_advertise_evidence(self):
        legacy = self.rig.succeed()
        with sqlite3.connect(self.rig.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET metrics_sha256=NULL WHERE job_id=?",
                       (legacy,))
        html = self.home()
        self.assertNotIn(self.shortcut(legacy), html)
        self.assertIn(f'href="/reports/{legacy}"', html)
        self.assertNotEqual(
            self.rig.request(f"/jobs/{legacy}/evidence")[0], 200
        )
        failed = self.rig.succeed()
        with sqlite3.connect(self.rig.root / "jobs.sqlite3") as db:
            db.execute("UPDATE jobs SET status='failed', error_code='analysis_failed' "
                       "WHERE job_id=?", (failed,))
        html = self.home()
        self.assertNotIn(self.shortcut(failed), html)
        self.assertNotIn(f'href="/reports/{failed}"', html)
        revoke_clip(self.rig.clip_id, self.rig.registry)
        html = self.home()
        self.assertNotIn(self.shortcut(legacy), html)
        self.assertNotIn(self.shortcut(failed), html)

    def test_evidence_gate_still_rejects_modified_metrics_after_shortcut_was_rendered(self):
        job_id = self.rig.succeed()
        html = self.home()
        self.assertIn(self.shortcut(job_id), html)
        self.rig.metrics_path.write_text('{"evidence":"changed"}', encoding="utf-8")
        status, headers, response = self.rig.request(
            f"/jobs/{job_id}/evidence"
        )
        self.assertEqual(status, 409)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(b"changed", response)
        self.assertNotIn(str(self.rig.root).encode(), response)


if __name__ == "__main__":
    unittest.main()
