"""Test-first route contract for the local analysis review workspace (#93).

All job statuses are synthetic. These tests do not exercise pose inference,
real rowing accuracy, live LLM output, or actual coach approval.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_job_status_steps as _fixture


class ResultsWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.rig = _fixture.JobStatusStagesTests(
            methodName="test_queued_running_and_success_stages_are_truthful"
        )
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def test_completed_job_presents_two_clear_actions_and_withheld_context(self):
        code, headers, page = self.rig.route("succeeded")
        self.assertEqual(code, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn(
            '<section class="result-workspace" aria-labelledby="result-heading">',
            page
        )
        self.assertIn('<h2 id="result-heading">Review your analysis</h2>', page)
        self.assertIn('class="result-actions"', page)
        self.assertEqual(page.count('<article class="result-action">'), 2)
        self.assertIn(f'href="/reports/{self.rig.job_id}"', page)
        self.assertIn(f'href="/jobs/{self.rig.job_id}/evidence"', page)
        self.assertIn('Open technique report', page)
        self.assertIn('Inspect saved evidence', page)
        self.assertIn('Coaching: <strong>withheld</strong>', page)
        self.assertIn('not coach-verified', page)
        self.assertNotIn('% complete', page)
        self.assertNotIn('synthetic test consent', page)
        self.assertNotIn('<meta http-equiv="refresh"', page)

    def test_queued_and_running_show_truthful_notice_without_result_actions(self):
        for status in ('queued', 'running'):
            with self.subTest(status=status):
                code, _, page = self.rig.route(status)
                self.assertEqual(code, 200)
                self.assertIn('class="status-callout status-processing"', page)
                self.assertIn('role="status" aria-label="Analysis progress"', page)
                self.assertIn('<meta http-equiv="refresh" content="2">', page)
                self.assertIn('<ol class="job-steps"', page)
                self.assertNotIn('class="result-workspace"', page)
                self.assertNotIn(f'href="/reports/{self.rig.job_id}"', page)
                self.assertNotIn(f'href="/jobs/{self.rig.job_id}/evidence"', page)
                self.assertNotIn('100%', page)

    def test_failure_explains_state_preserves_retry_without_false_results(self):
        for error in ('analysis_failed', 'unsupported_video'):
            with self.subTest(error=error):
                code, _, page = self.rig.route("failed", error=error)
                self.assertEqual(code, 200)
                self.assertIn('class="status-callout status-error"', page)
                self.assertIn('role="alert"', page)
                self.assertIn('Analysis could not finish', page)
                self.assertNotIn('class="result-workspace"', page)
                self.assertNotIn(f'href="/reports/{self.rig.job_id}"', page)
                self.assertNotIn(f'href="/jobs/{self.rig.job_id}/evidence"', page)
                if error == 'analysis_failed':
                    self.assertIn('Retry analysis', page)
                    self.assertIn('action="/jobs"', page)
                    self.assertIn('name="csrf"', page)
                else:
                    self.assertNotIn('Retry analysis', page)

    def test_responsive_styles_and_json_route_are_unchanged(self):
        _, _, page = self.rig.route('succeeded')
        self.assertIn('.result-actions', page)
        self.assertIn('.result-action', page)
        self.assertIn('.result-video', page)
        self.assertIn('.status-callout', page)
        self.assertIn('@media (max-width: 720px)', page)
        self.assertIn(':focus-visible', page)
        self.assertNotIn('<script', page)
        code, headers, body = self.rig.route('running', api=True)
        self.assertEqual(code, 200)
        self.assertIn('application/json', headers['Content-Type'])
        self.assertNotIn('result-workspace', body)


if __name__ == "__main__":
    unittest.main()
