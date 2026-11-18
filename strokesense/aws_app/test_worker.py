"""Offline contract tests for the Fargate CPU worker (no AWS or ONNX needed)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from aws_app import worker


JOB = "a" * 32
USER = "b" * 24
BUCKET = "strokesense-aws-test"
INPUT = f"uploads/{USER}/{JOB}/original.mp4"
REPORT = f"reports/free/{USER}/{JOB}/report.json"


def config(**changes):
    settings = {
        "STROKESENSE_JOB_ID": JOB,
        "STROKESENSE_USER_HASH": USER,
        "STROKESENSE_S3_BUCKET": BUCKET,
        "STROKESENSE_INPUT_KEY": INPUT,
        "STROKESENSE_REPORT_KEY": REPORT,
    }
    settings.update(changes)
    return settings


class FakeS3:
    def __init__(self, data=b"synthetic bytes for contract test", expected_length=None):
        self.data = data
        self.expected_length = len(data) if expected_length is None else expected_length
        self.puts = []
        self.gets = []

    def head_object(self, **kwargs):
        self.gets.append(("head", kwargs))
        return {"ContentLength": self.expected_length}

    def get_object(self, **kwargs):
        self.gets.append(("get", kwargs))
        return {"Body": io.BytesIO(self.data)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def valid_pipeline(video: Path, results: Path, timeout: int):
    assert video.read_bytes() == b"synthetic bytes for contract test"
    assert timeout == worker.DEFAULT_ANALYSIS_TIMEOUT_SECONDS
    directory = results / "analysis"
    directory.mkdir()
    (directory / "report.html").write_text(
        "<html><body><h1>Measured technique</h1></body></html>", encoding="utf-8"
    )
    (directory / "metrics.json").write_text(
        json.dumps({"rowers": [{"seat": "R1", "strokes": [{"catch_seconds": 1}]}]}),
        encoding="utf-8",
    )


class CpuWorkerContractTests(unittest.TestCase):
    def test_uses_private_input_and_commits_valid_report_last(self):
        store = FakeS3()
        worker.run_job(env=config(), s3=store, pipeline=valid_pipeline)
        self.assertEqual([action for action, _ in store.gets], ["head", "get"])
        self.assertEqual(len(store.puts), 1)
        saved = store.puts[0]
        self.assertEqual(saved["Bucket"], BUCKET)
        self.assertEqual(saved["Key"], REPORT)
        self.assertEqual(saved["ServerSideEncryption"], "AES256")
        self.assertIn("application/json", saved["ContentType"])
        payload = json.loads(saved["Body"])
        self.assertEqual(payload["job_id"], JOB)
        self.assertEqual(payload["tier"], "free")
        self.assertFalse(payload["coach_validated"])
        self.assertIn("Measured technique", payload["report_html"])
        self.assertEqual(payload["metrics"]["rowers"][0]["seat"], "R1")

    def test_rejects_report_from_another_owner_or_paid_lane(self):
        for bad in (
            config(STROKESENSE_USER_HASH="c" * 24),
            config(STROKESENSE_INPUT_KEY=f"uploads/{USER}/{'c' * 32}/original.mp4"),
            config(STROKESENSE_REPORT_KEY=f"reports/paid/{USER}/{JOB}/report.json"),
            config(STROKESENSE_REPORT_KEY=f"reports/free/{'c' * 24}/{JOB}/report.json"),
        ):
            with self.subTest(bad=bad):
                store = FakeS3()
                with self.assertRaises(worker.WorkerError):
                    worker.run_job(env=bad, s3=store, pipeline=valid_pipeline)
                self.assertEqual(store.gets, [])
                self.assertEqual(store.puts, [])

    def test_rejects_oversized_media_before_download(self):
        store = FakeS3(expected_length=worker.FREE_MAX_VIDEO_BYTES + 1)
        with self.assertRaisesRegex(worker.WorkerError, "invalid_media_size"):
            worker.run_job(env=config(), s3=store, pipeline=valid_pipeline)
        self.assertEqual([action for action, _ in store.gets], ["head"])
        self.assertEqual(store.puts, [])

    def test_rejects_truncated_media_and_does_not_publish(self):
        store = FakeS3(expected_length=999)
        with self.assertRaisesRegex(worker.WorkerError, "incomplete_video_download"):
            worker.run_job(env=config(), s3=store, pipeline=valid_pipeline)
        self.assertEqual(store.puts, [])

    def test_pipeline_failure_does_not_publish(self):
        store = FakeS3()

        def fail(*_args):
            raise worker.WorkerError("analysis_failed")

        with self.assertRaisesRegex(worker.WorkerError, "analysis_failed"):
            worker.run_job(env=config(), s3=store, pipeline=fail)
        self.assertEqual(store.puts, [])

    def test_missing_or_empty_report_does_not_publish(self):
        for case in ("missing", "empty"):
            store = FakeS3()

            def pipeline(_video, results, _timeout):
                folder = results / "run"
                folder.mkdir()
                if case == "empty":
                    (folder / "report.html").write_text("<html></html>", encoding="utf-8")
                    (folder / "metrics.json").write_text(
                        '{"rowers":[{"strokes":[]}]}', encoding="utf-8"
                    )

            with self.subTest(case=case):
                with self.assertRaises(worker.WorkerError):
                    worker.run_job(env=config(), s3=store, pipeline=pipeline)
                self.assertEqual(store.puts, [])

    def test_real_command_uses_existing_bounded_cpu_analyzer(self):
        with patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            worker._run_real_pipeline(Path("/tmp/test.mp4"), Path("/tmp/results"), 60)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], [worker.sys.executable, "-u", "-m", "strokesense.cli"])
        self.assertIn("--bounded-media", args)
        self.assertIn("--dominant-crew", args)
        self.assertIn("--threads", args)
        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_real_command_failure_remains_failure(self):
        with patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)):
            with self.assertRaisesRegex(worker.WorkerError, "analysis_failed"):
                worker._run_real_pipeline(Path("/tmp/test.mp4"), Path("/tmp/results"), 60)


if __name__ == "__main__":
    unittest.main()
