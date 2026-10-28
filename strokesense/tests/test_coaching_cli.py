"""Offline-only CLI contract tests; all approvals and outputs are fictional fixtures.

Do not confuse these fixtures with genuine coach review or live LLM execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_validation import trusted_synthetic_fixture


def rehash(snapshot):
    payload = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


class CoachingCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="coaching-cli-synthetic-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.snapshot, self.candidate, self.cues = trusted_synthetic_fixture()
        self.metrics = self.base / "metrics.json"
        self.cues_path = self.base / "cues.json"
        self.candidates = self.base / "candidates.json"
        self.save()

    def save(self, candidates=None):
        self.metrics.write_text(json.dumps({"evidence": self.snapshot}), encoding="utf-8")
        self.cues_path.write_text(json.dumps(self.cues), encoding="utf-8")
        self.candidates.write_text(
            json.dumps([self.candidate] if candidates is None else candidates),
            encoding="utf-8",
        )

    def run_cli(self, *extra, live=False):
        args = [
            sys.executable, "-m", "strokesense.coaching_cli",
            "--metrics", str(self.metrics), "--cues", str(self.cues_path),
        ]
        args += ["--live"] if live else ["--candidates", str(self.candidates)]
        args += list(extra)
        env = dict(os.environ)
        # The offline CLI must not be dependent on live credential availability.
        env.pop("STROKESENSE_LLM_API_KEY", None)
        env.pop("STROKESENSE_LLM_MODEL", None)
        run = subprocess.run(args, cwd=ROOT, env=env, text=True,
                             capture_output=True, check=False, timeout=20)
        try:
            result = json.loads(run.stdout)
        except ValueError:
            self.fail("Coaching CLI must return parseable JSON; stderr=" + run.stderr[-350:])
        self.assertNotIn(str(self.base), run.stdout)
        return run.returncode, result, run

    def test_offline_second_attempt_corrects_and_releases_only_checked_candidate(self):
        incorrect = copy.deepcopy(self.candidate)
        incorrect["observed_count"] = 99
        self.save([incorrect, self.candidate])
        code, answer, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(answer["mode"], "offline_fixture")
        self.assertEqual(answer["status"], "released")
        self.assertEqual(answer["attempts"], 2)
        self.assertEqual(answer["released"], self.candidate)
        self.assertIn("free_text_unverified", answer["warnings"])
        self.assertNotIn("live", answer["warnings"])

    def test_offline_persistent_fabrication_is_withheld_with_no_rejected_text(self):
        fake = copy.deepcopy(self.candidate)
        fake["stroke_ids"] = ["fictional-stroke"]
        fake["explanation"] = "SECRET PRIVATE CLAIM SHOULD NOT LEAK"
        self.save([fake, fake, fake])
        code, answer, run = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(answer["mode"], "offline_fixture")
        self.assertEqual(answer["status"], "withheld")
        self.assertEqual(answer["attempts"], 3)
        self.assertIsNone(answer["released"])
        self.assertIn("unknown_stroke", answer["errors"])
        self.assertNotIn("SECRET PRIVATE CLAIM", run.stdout + run.stderr)

    def test_realistic_unreviewed_snapshot_cannot_release_even_with_approved_claim(self):
        finding = self.snapshot["findings"][0]
        finding["coaching_eligible"] = False
        finding["eligible_strokes"] = None
        finding["status"] = "candidate_unreviewed"
        rehash(self.snapshot)
        self.save()
        code, answer, _ = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(answer["status"], "withheld")
        self.assertIn("insufficient_evidence", answer["errors"])

    def test_offline_inputs_bounded_and_fail_closed_with_safe_errors(self):
        for payload in ("not-json", "[]" * 400000):
            with self.subTest(payload=payload[:10]):
                self.metrics.write_text(payload, encoding="utf-8")
                code, answer, run = self.run_cli()
                self.assertEqual(code, 2)
                self.assertEqual(answer["status"], "withheld")
                self.assertEqual(answer["attempts"], 0)
                self.assertEqual(answer["errors"], ["invalid_input"])
                self.assertNotIn(payload[:20], run.stderr)
        self.save()
        for attempts in ([], [self.candidate] * 4):
            with self.subTest(attempts=len(attempts)):
                self.save(attempts)
                code, answer, _ = self.run_cli()
                self.assertEqual(code, 2)
                self.assertEqual(answer["errors"], ["invalid_input"])

    def test_byte_caps_reject_otherwise_valid_large_json_files(self):
        large_candidate = copy.deepcopy(self.candidate)
        large_candidate["explanation"] = "A" * (256 * 1024)
        self.save([large_candidate])
        code, answer, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(answer["errors"], ["invalid_input"])
        self.save()
        self.metrics.write_text(json.dumps({
            "evidence": self.snapshot,
            "ignored_padding": "X" * (16 * 1024 * 1024),
        }), encoding="utf-8")
        code, answer, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(answer["errors"], ["invalid_input"])

    def test_no_network_without_live_flag_and_no_implicit_output_mutation(self):
        old_metrics = self.metrics.read_bytes()
        old_cues = self.cues_path.read_bytes()
        code, answer, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(answer["mode"], "offline_fixture")
        self.assertEqual(self.metrics.read_bytes(), old_metrics)
        self.assertEqual(self.cues_path.read_bytes(), old_cues)
        self.assertFalse((self.base / "coaching.json").exists())

    def test_explicit_live_requires_config_and_never_impersonates_a_fixture(self):
        code, answer, run = self.run_cli(live=True)
        self.assertEqual(code, 2)
        self.assertEqual(answer["mode"], "live_provider")
        self.assertEqual(answer["status"], "withheld")
        self.assertEqual(answer["attempts"], 0)
        self.assertEqual(answer["errors"], ["missing_configuration"])
        self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
