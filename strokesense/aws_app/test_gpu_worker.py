"""Offline tests for a genuine paid GPU report writer and hard CUDA requirement."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aws_app import gpu_worker, worker
from aws_app.test_worker import FakeS3, config as cpu_config, media_pipeline


def paid_config(**changes):
    settings = cpu_config(
        STROKESENSE_REPORT_KEY=cpu_config()["STROKESENSE_REPORT_KEY"].replace("/free/", "/paid/"),
        STROKESENSE_PAID_GPU_WORKER_ENABLED="true",
    )
    settings.update(changes)
    return settings


def pass_preflight(_model):
    return {"provider": "CUDAExecutionProvider",
            "cuda_node_execution_verified": True,
            "provider_audit": {"cuda_nodes": 80, "cuda_conv_nodes": 40, "cpu_structural_nodes": 2},
            "gpu_memory_total_mib": 3072, "gpu_memory_free_mib": 2600}


class GpuWorkerTests(unittest.TestCase):
    def test_paid_gpu_writes_private_report_last(self):
        store = FakeS3()
        with patch("aws_app.gpu_model_integrity.verify_gpu_model"):
            gpu_worker.run_job(env=paid_config(), s3=store, pipeline=media_pipeline,
                               preflight=pass_preflight)
        keys = [record["Key"] for record in store.puts]
        prefix = paid_config()["STROKESENSE_REPORT_KEY"].removesuffix("report.json")
        self.assertEqual(keys[-1], prefix + "report.json")
        self.assertIn(prefix + "annotated.mp4", keys)
        self.assertIn(prefix + "runtime-metrics.json", keys)
        report = json.loads(store.puts[-1]["Body"])
        self.assertEqual(report["schema_version"], "strokesense-paid-report-v1")
        self.assertEqual(report["tier"], "paid")
        self.assertIn("CUDA ONNX", report["analysis_method"])
        metrics = json.loads(next(o["Body"] for o in store.puts if
                                  o["Key"].endswith("runtime-metrics.json")))
        self.assertEqual(metrics["gpu_execution_provider"], "CUDAExecutionProvider")
        self.assertTrue(metrics["cuda_node_execution_verified"])
        self.assertGreater(metrics["cuda_provider_audit"]["cuda_conv_nodes"], 0)
        self.assertEqual(metrics["gpu_memory_total_mib"], 3072)

    def test_gpu_worker_rejects_unapproved_and_free_jobs(self):
        for changes in [
            {"STROKESENSE_PAID_GPU_WORKER_ENABLED": ""},
            {"STROKESENSE_REPORT_KEY": cpu_config()["STROKESENSE_REPORT_KEY"]},
            {"STROKESENSE_INPUT_KEY": "uploads/anothersub/not-owned/original.mp4"},
        ]:
            store = FakeS3()
            with self.subTest(changes=changes), self.assertRaises(worker.WorkerError):
                gpu_worker.run_job(env=paid_config(**changes), s3=store,
                                   pipeline=media_pipeline, preflight=pass_preflight)
            self.assertEqual(store.puts, [])

    def test_no_cuda_means_no_video_download_or_report(self):
        store = FakeS3()
        with patch("aws_app.gpu_model_integrity.verify_gpu_model"):
            with self.assertRaisesRegex(Exception, "cuda_provider_unavailable"):
                gpu_worker.run_job(env=paid_config(), s3=store,
                                   pipeline=media_pipeline,
                                   preflight=lambda _model: (_ for _ in ()).throw(
                                       gpu_worker.GpuPreflightError("cuda_provider_unavailable")))
        self.assertEqual(store.gets, [])
        self.assertEqual(store.puts, [])

    def test_unverified_cuda_profile_blocks_video_download_and_report(self):
        store = FakeS3()
        with patch("aws_app.gpu_model_integrity.verify_gpu_model"):
            with self.assertRaisesRegex(worker.WorkerError, "gpu_cuda_execution_unverified"):
                gpu_worker.run_job(env=paid_config(), s3=store,
                                   pipeline=media_pipeline,
                                   preflight=lambda _model: {"provider": "CUDAExecutionProvider"})
        self.assertEqual(store.gets, [])
        self.assertEqual(store.puts, [])

    def test_gpu_subprocess_enforces_cuda_in_child_environment(self):
        with TemporaryDirectory() as directory:
            video = Path(directory) / "input.mp4"
            output = Path(directory) / "output"
            completed = SimpleNamespace(returncode=0)
            with patch.object(gpu_worker.subprocess, "run", return_value=completed) as launch:
                gpu_worker.run_cuda_pipeline(video, output, 300)
            args = launch.call_args.args[0]
            kwargs = launch.call_args.kwargs
            self.assertEqual(args[:5], [gpu_worker.sys.executable, "-u", "-m",
                                         "strokesense.cli", str(video)])
            self.assertEqual(kwargs["env"]["STROKESENSE_REQUIRE_CUDA"], "1")
            self.assertIn("--bounded-media", args)
            self.assertEqual(kwargs["timeout"], 300)

    def test_gpu_report_still_bounded_to_750mb_input(self):
        store = FakeS3(expected_length=750_000_001)
        with patch("aws_app.gpu_model_integrity.verify_gpu_model"):
            with self.assertRaises(worker.WorkerError):
                gpu_worker.run_job(env=paid_config(), s3=store,
                                   pipeline=media_pipeline, preflight=pass_preflight)
        self.assertEqual(store.puts, [])


if __name__ == "__main__":
    unittest.main()
