"""Standalone paid GPU worker for a future ECS G6f task (never Fargate).

Runs the real StrokeSense video pipeline with ONNX CUDA required, then writes
private paid-tier artifacts and the report LAST. An approved GPU-capable image,
ECS task and verified payment/dispatch system are still prerequisites.

This entry point deliberately refuses CPU-only hosts and free-tier paths.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping

from .core import PAID_VIDEO_BYTES
from .gpu_preflight import GpuPreflightError, validate_gpu_runtime
from . import worker

LOGGER = logging.getLogger(__name__)
GPU_JOB_TIMEOUT_SECONDS = 3300
_ENV_ENABLED = "STROKESENSE_PAID_GPU_WORKER_ENABLED"


def gpu_job_config(config: Mapping[str, str]) -> tuple[str, str, str, str]:
    """Require fixed owner/job-isolated keys. No S3 prefix from a user request."""
    if config.get(_ENV_ENABLED) != "true":
        raise worker.WorkerError("gpu_worker_disabled")
    job = config.get("STROKESENSE_JOB_ID", "")
    uid = config.get("STROKESENSE_USER_HASH", "")
    bucket = config.get("STROKESENSE_S3_BUCKET", "")
    input_key = config.get("STROKESENSE_INPUT_KEY", "")
    report_key = config.get("STROKESENSE_REPORT_KEY", "")
    if not worker._JOB_ID.fullmatch(job) or not worker._USER_HASH.fullmatch(uid):
        raise worker.WorkerError("invalid_job_identity")
    if not worker._BUCKET.fullmatch(bucket):
        raise worker.WorkerError("invalid_storage_configuration")
    if not any(input_key == f"uploads/{uid}/{job}/original{suffix}" for suffix in worker._EXTENSIONS):
        raise worker.WorkerError("invalid_input_key")
    if report_key != f"reports/paid/{uid}/{job}/report.json":
        raise worker.WorkerError("invalid_paid_report_key")
    return bucket, input_key, report_key, Path(input_key).suffix


def run_cuda_pipeline(video: Path, output: Path, timeout: int) -> None:
    """Run real pose tracking while *requiring* ONNX CUDA provider in child."""
    command = [
        sys.executable, "-u", "-m", "strokesense.cli", str(video),
        "--out", str(output), "--fps", "12", "--dominant-crew",
        "--threads", "2", "--fresh", "--bounded-media",
    ]
    environment = dict(os.environ)
    environment["STROKESENSE_REQUIRE_CUDA"] = "1"
    try:
        completed = subprocess.run(
            command, timeout=timeout, check=False,
            cwd=str(Path(__file__).resolve().parents[1]), env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise worker.WorkerError("gpu_analysis_timeout") from exc
    except OSError as exc:
        raise worker.WorkerError("gpu_analysis_process_unavailable") from exc
    if completed.returncode != 0:
        raise worker.WorkerError("gpu_analysis_failed")


def run_job(
    *, env: Mapping[str, str] | None = None,
    s3: Any = None,
    pipeline: Callable[[Path, Path, int], None] = run_cuda_pipeline,
    preflight: Callable[[Path], Any] = validate_gpu_runtime,
) -> None:
    """One paid ECS task. Injection permits CPU-only, no-network unit tests."""
    config = os.environ if env is None else env
    bucket, input_key, report_key, extension = gpu_job_config(config)
    model = Path(__file__).resolve().parents[1] / "models" / "yolo11n-pose.onnx"
    # The container build pins the model by sha256. The runtime rechecks its
    # digest rather than downloading or trusting arbitrary user-supplied paths.
    from .gpu_model_integrity import verify_gpu_model
    verify_gpu_model(model)
    initial_gpu = preflight(model)  # Verify CUDA kernels before any customer data access.
    if not isinstance(initial_gpu, dict) or initial_gpu.get("cuda_node_execution_verified") is not True:
        raise worker.WorkerError("gpu_cuda_execution_unverified")
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    raw_timeout = config.get("STROKESENSE_GPU_TIMEOUT_SECONDS", str(GPU_JOB_TIMEOUT_SECONDS))
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise worker.WorkerError("invalid_gpu_timeout") from exc
    if type(timeout) is not int or not 30 <= timeout <= GPU_JOB_TIMEOUT_SECONDS:
        raise worker.WorkerError("invalid_gpu_timeout")

    with tempfile.TemporaryDirectory(prefix="strokesense-paid-gpu-") as folder:
        started = time.perf_counter()
        root = Path(folder)
        source = root / ("original" + extension)
        output = root / "results"
        output.mkdir(mode=0o700)
        worker._download_bounded(s3, bucket, input_key, source, max_bytes=PAID_VIDEO_BYTES)
        clip_duration_ms = worker._video_duration_ms(source)
        cpu_begin = worker._child_cpu_seconds()
        analysis_begin = time.perf_counter()
        pipeline(source, output, timeout)
        analysis_wall_ms = int((time.perf_counter() - analysis_begin) * 1000)
        payload = worker._report_payload(output, config["STROKESENSE_JOB_ID"], tier="paid")
        # Media manifest + frames/MP4, then metrics; report.json is the commit.
        worker._publish_media(s3, bucket, report_key, output)
        preflight_data = preflight(model)
        if not isinstance(preflight_data, dict) or preflight_data.get("cuda_node_execution_verified") is not True:
            raise worker.WorkerError("gpu_cuda_execution_unverified")
        timings: dict[str, Any] = {
            "schema_version": 1,
            "job_id": config["STROKESENSE_JOB_ID"],
            "analysis_wall_ms": analysis_wall_ms,
            "cpu_time_ms": int(max(0, (worker._child_cpu_seconds() - cpu_begin) * 1000)),
            "worker_wall_ms": int((time.perf_counter() - started) * 1000),
            "gpu_execution_provider": "CUDAExecutionProvider",
            "cuda_node_execution_verified": True,
            "cuda_provider_audit": preflight_data.get("provider_audit", {}),
            "gpu_memory_total_mib": preflight_data["gpu_memory_total_mib"],
            "gpu_memory_free_mib": preflight_data["gpu_memory_free_mib"],
        }
        if clip_duration_ms is not None:
            timings["video_duration_ms"] = clip_duration_ms
        s3.put_object(
            Bucket=bucket, Key=report_key.removesuffix("report.json") + "runtime-metrics.json",
            Body=json.dumps(timings, allow_nan=False, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256", CacheControl="private, no-store",
        )
        s3.put_object(
            Bucket=bucket, Key=report_key, Body=payload,
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256", CacheControl="private, no-store",
        )
        LOGGER.info("Paid GPU video analysis saved (report bytes %s).", len(payload))


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        run_job()
    except (worker.WorkerError, GpuPreflightError) as exc:
        LOGGER.error("Paid GPU job failed (%s), report not committed.", str(exc))
        return 2
    except Exception:
        # Do not disclose S3 object keys, model paths or customer metadata.
        LOGGER.error("Paid GPU job failed (internal_error), report not committed.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
