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


# Fabricated fixtures only. "reviewed" below is a simulated label, not human review.
_REVIEW_COLUMNS = (
    "schema_version", "seat_id", "seat", "stroke_id", "stroke_index",
    "fault_code", "catch_seconds", "video_seek_seconds", "predicted",
    "coach_fault_present", "coach_comments", "review_status",
)


def _review_csv(rows, *, header=_REVIEW_COLUMNS):
    import csv
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(k, "") for k in header])
    return buf.getvalue()


def _review_row(index, *, actual="0", predicted="0", status="reviewed"):
    return dict(schema_version="1", seat_id="seat-fixture", seat="Stroke",
                stroke_id=f"stroke-{index}", stroke_index=str(index),
                fault_code="early_arms", catch_seconds=str(index),
                video_seek_seconds="", predicted=predicted,
                coach_fault_present=actual, coach_comments="",
                review_status=status)


class ReviewCsvEvaluationTests(unittest.TestCase):
    def run_csv(self, text, *, args=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private-local-review.csv"
            path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
            argv = ["--review-csv", "--clip-id", "private-clip",
                    "--group-id", "private-session", "--split", "heldout",
                    str(path)] if args is None else args + [str(path)]
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = evaluation.main(argv)
                except SystemExit as exc:
                    code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_review_csv_counts_full_confusion_matrix_without_source_ids(self):
        values = [
            _review_row(1, actual="1", predicted="1"),  # synthetic TP
            _review_row(2, actual="0", predicted="1"),  # synthetic FP
            _review_row(3, actual="1", predicted="0"),  # synthetic FN
            _review_row(4, actual="0", predicted="0"),  # synthetic TN
        ]
        code, out, err = self.run_csv(_review_csv(values))
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        bucket = report["by_split"]["heldout"]["early_arms"]
        self.assertEqual([bucket[k] for k in ("tp", "fp", "fn", "tn")],
                         [1, 1, 1, 1])
        self.assertEqual(bucket["precision_denominator"], 2)
        self.assertEqual(bucket["recall_denominator"], 2)
        self.assertEqual(report["labels_independently_verified"], False)
        self.assertNotIn("private-", out)
        self.assertNotIn("coach_comments", out)

    def test_default_unreviewed_and_incomplete_reviews_fail_closed(self):
        for change in (
            {"review_status": "unreviewed", "coach_fault_present": ""},
            {"coach_fault_present": ""},
            {"coach_fault_present": "true"},
            {"predicted": "yes"},
            {"schema_version": "2"},
            {"fault_code": "not_a_real_fault"},
        ):
            row = _review_row(1)
            row.update(change)
            with self.subTest(change=change):
                code, out, err = self.run_csv(_review_csv([row]))
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertNotIn("private-", err)
                self.assertNotIn("Traceback", err)

    def test_duplicate_or_unknown_headers_and_inconsistent_rows_rejected(self):
        row = _review_row(1)
        variants = (
            _review_csv([row], header=_REVIEW_COLUMNS + ("seat",)),
            _review_csv([row], header=_REVIEW_COLUMNS[:-1]),
            _review_csv([row, row]),
            _review_csv([]),
        )
        for csv_text in variants:
            with self.subTest(csv_text=csv_text[:55]):
                code, out, _ = self.run_csv(csv_text)
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")

    def test_binary_null_and_malformed_quoted_rows_fail_safely(self):
        raw = _review_row(1)
        raw["seat"] = "fixture" + chr(0) + "invisible"
        bad_nul = _review_csv([raw])
        good = _review_csv([_review_row(1)])
        bad_quote = good + '"unterminated,field'
        for bad in (bad_nul, bad_quote):
            with self.subTest(kind="null" if bad is bad_nul else "quote"):
                code, out, err = self.run_csv(bad)
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertNotIn("private-", err)
                self.assertNotIn("Traceback", err)

    def test_review_csv_requires_explicit_group_clip_and_split(self):
        code, out, _ = self.run_csv(_review_csv([_review_row(1)]),
                                    args=["--review-csv"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")



if __name__ == "__main__":
    unittest.main()
