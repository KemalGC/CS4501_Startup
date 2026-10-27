"""Synthetic offline CLI contract: JSON summary without disclosing source IDs."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import evaluation


def _valid_row():
    return {
        "clip_id": "private-clip-identifier", "seat_id": "private-seat",
        "stroke_id": "private-stroke", "fault_code": "early_arms",
        "actual": True, "predicted": True, "review_status": "reviewed",
        "group_id": "private-session", "split": "heldout",
    }


class EvaluationCliTests(unittest.TestCase):
    def run_cli(self, path):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            # Missing CLI behavior fails an assertion, not an import error.
            code = getattr(evaluation, "main", lambda _: 99)([str(path)])
        return code, out.getvalue(), err.getvalue()

    def test_valid_offline_json_prints_only_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewed.json"
            path.write_text(json.dumps([_valid_row()]), encoding="utf-8")
            code, out, err = self.run_cli(path)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        result = json.loads(out)
        self.assertEqual(result["by_split"]["heldout"]["early_arms"]["tp"], 1)
        self.assertNotIn("private-clip-identifier", out)
        self.assertNotIn("private-session", out)

    def test_bad_input_exits_without_private_paths_or_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = [b"", b"not json", b"\xff", b"x" * (2 * 1024 * 1024 + 1),
                        json.dumps([{**_valid_row(), "review_status": "unreviewed"}]).encode()]
            for i, bad in enumerate(examples):
                path = root / f"private-error-name-{i}.json"
                path.write_bytes(bad)
                with self.subTest(i=i):
                    code, out, err = self.run_cli(path)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(out, "")
                    self.assertNotIn(str(path), err)
                    self.assertNotIn("private", err.lower())
                    self.assertNotIn("traceback", err.lower())
            absent = root / "absent-private-file.json"
            code, out, err = self.run_cli(absent)
            self.assertNotEqual(code, 0)
            self.assertEqual(out, "")
            self.assertNotIn(str(absent), err)


if __name__ == "__main__":
    unittest.main()
