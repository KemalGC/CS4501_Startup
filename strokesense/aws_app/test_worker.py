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
        body = kwargs["Body"]
        kwargs["Body"] = body.read() if hasattr(body, "read") else body
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


def media_pipeline(video: Path, results: Path, timeout: int):
    valid_pipeline(video, results, timeout)
    folder = results / "analysis"
    (folder / "original_annotated.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"video data")
    for name in ("seat_R1_catch.jpg", "fault_1_early_body.jpg", "fault_1_early_body_before.jpg"):
        (folder / name).write_bytes(b"\xff\xd8\xff\xe0jpeg data\xff\xd9")
    (folder / "mistake_frames.json").write_text(json.dumps({
        "version": 1,
        "rowers": {"R1": {
            "snapshots": [{"label": "Catch reference", "time_seconds": 1.2, "filename": "seat_R1_catch.jpg"}],
            "mistake_sequences": [{"code": "early_body", "stroke": 2, "frames": [
                {"label": "Before", "time_seconds": 1.1, "filename": "fault_1_early_body_before.jpg"},
                {"label": "Flagged moment", "time_seconds": 1.3, "filename": "fault_1_early_body.jpg"},
            ]}],
        }},
    }), encoding="utf-8")


class CpuWorkerContractTests(unittest.TestCase):
    def test_uploaded_media_are_private_bounded_and_report_is_last(self):
        store = FakeS3()
        worker.run_job(env=config(), s3=store, pipeline=media_pipeline)
        keys = [obj["Key"] for obj in store.puts]
        prefix = REPORT.removesuffix("report.json")
        self.assertEqual(keys[-3:], [prefix + "artifacts.json", prefix + "runtime-metrics.json", REPORT])
        self.assertEqual(set(keys[:-3]), {
            prefix + "annotated.mp4",
            prefix + "frames/seat_R1_catch.jpg",
            prefix + "frames/fault_1_early_body.jpg",
            prefix + "frames/fault_1_early_body_before.jpg",
        })
        for obj in store.puts:
            self.assertEqual(obj["ServerSideEncryption"], "AES256")
            self.assertEqual(obj["CacheControl"], "private, no-store")
            self.assertEqual(obj["Bucket"], BUCKET)
        self.assertEqual(next(obj for obj in store.puts if obj["Key"].endswith("annotated.mp4"))["ContentType"], "video/mp4")
        manifest = json.loads(store.puts[-3]["Body"])
        self.assertTrue(manifest["video_available"])
        self.assertEqual(manifest["rowers"]["R1"]["mistake_sequences"][0]["frames"][1]["label"], "Flagged moment")
        timing = json.loads(store.puts[-2]["Body"])
        self.assertEqual(timing["job_id"], JOB)
        self.assertNotIn("artifacts", json.loads(store.puts[-1]["Body"]))

    def test_unsafe_gallery_filename_never_publishes_anything(self):
        def unsafe(video, results, timeout):
            media_pipeline(video, results, timeout)
            manifest = results / "analysis" / "mistake_frames.json"
            raw = json.loads(manifest.read_text())
            raw["rowers"]["R1"]["snapshots"][0]["filename"] = "../../another-user/photo.jpg"
            manifest.write_text(json.dumps(raw))
        store = FakeS3()
        with self.assertRaisesRegex(worker.WorkerError, "invalid_media_manifest"):
            worker.run_job(env=config(), s3=store, pipeline=unsafe)
        self.assertEqual(store.puts, [])

    def test_media_upload_failure_does_not_commit_success_report(self):
        store = FakeS3()
        def fail_media(**kwargs):
            if kwargs["Key"].endswith(".jpg"):
                raise OSError("fake S3 write failure")
            store.puts.append(kwargs)
        with patch.object(store, "put_object", side_effect=fail_media):
            with self.assertRaises(OSError):
                worker.run_job(env=config(), s3=store, pipeline=media_pipeline)
        self.assertTrue(all(item["Key"] != REPORT for item in store.puts))

    def test_oversized_annotated_video_does_not_commit_success(self):
        store = FakeS3()
        with patch.object(worker.artifacts, "MAX_VIDEO_BYTES", 12):
            with self.assertRaisesRegex(worker.WorkerError, "invalid_media_artifact_size"):
                worker.run_job(env=config(), s3=store, pipeline=media_pipeline)
        self.assertEqual(store.puts, [])

    def test_uses_private_input_and_commits_valid_report_last(self):
        store = FakeS3()
        worker.run_job(env=config(), s3=store, pipeline=valid_pipeline)
        self.assertEqual([action for action, _ in store.gets], ["head", "get"])
        self.assertEqual(len(store.puts), 2)
        timing = store.puts[0]
        self.assertEqual(timing["Key"], REPORT.replace("report.json", "runtime-metrics.json"))
        measured = json.loads(timing["Body"])
        self.assertEqual(measured["job_id"], JOB)
        self.assertGreaterEqual(measured["analysis_wall_ms"], 0)
        self.assertGreaterEqual(measured["cpu_time_ms"], 0)
        saved = store.puts[1]
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
