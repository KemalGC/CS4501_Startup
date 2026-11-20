"""Fail-closed ONNX/CUDA readiness check for a FUTURE GPU worker image.

Running this manually never launches AWS compute, schedules a GPU job, or
updates any paid credit. Tests inject fake dependencies on CPU-only hosts.
The real GPU worker and billing adapter have NOT been implemented.
"""
from __future__ import annotations

import argparse
import importlib
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
GPU_PROVIDER = "CUDAExecutionProvider"
GPU_MIN_TOTAL_MIB = 2800  # The target g6f.large exposes approximately 3 GiB.
GPU_MIN_FREE_MIB = 1800


class GpuPreflightError(RuntimeError):
    """Fixed diagnostic categories; no user media paths in error details."""


def _device_memory(run: Callable[..., Any] = subprocess.run) -> tuple[int, int]:
    try:
        result = run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GpuPreflightError("nvidia_driver_unavailable") from exc
    if result.returncode != 0:
        raise GpuPreflightError("nvidia_driver_unavailable")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # A one-partition, one-job GPU model. Multiple devices require new review.
    if len(lines) != 1:
        raise GpuPreflightError("unexpected_gpu_partition_count")
    fields = [v.strip() for v in lines[0].split(",")]
    if len(fields) != 2 or any(not value.isdecimal() for value in fields):
        raise GpuPreflightError("invalid_gpu_memory_report")
    total, free = int(fields[0]), int(fields[1])
    if total < GPU_MIN_TOTAL_MIB or free < GPU_MIN_FREE_MIB or free > total:
        raise GpuPreflightError("insufficient_gpu_memory")
    return total, free


def validate_gpu_runtime(model: Path, *, run: Callable[..., Any] = subprocess.run,
                         import_module: Callable[[str], Any] = importlib.import_module) -> dict[str, Any]:
    """Prove CUDA is the first active ONNX provider for the specified model."""
    if model.suffix.lower() != ".onnx" or not model.is_file():
        raise GpuPreflightError("model_not_found")
    total, free = _device_memory(run)
    try:
        ort = import_module("onnxruntime")
        available = ort.get_available_providers()
        if GPU_PROVIDER not in available:
            raise GpuPreflightError("cuda_provider_unavailable")
        session = ort.InferenceSession(str(model), providers=[GPU_PROVIDER])
        active = session.get_providers()
        if not isinstance(active, list) or not active or active[0] != GPU_PROVIDER:
            raise GpuPreflightError("cuda_provider_not_active")
        # Do not silently allow an unexpected CPU-only session.
        if callable(getattr(session, "disable_fallback", None)):
            session.disable_fallback()
    except GpuPreflightError:
        raise
    except Exception as exc:
        raise GpuPreflightError("cuda_session_initialization_failed") from exc
    return {"provider": GPU_PROVIDER, "gpu_memory_total_mib": total,
            "gpu_memory_free_mib": free, "model_loaded": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GPU readiness; does not run paid inference.")
    parser.add_argument("--model", required=True, type=Path, help="Locally mounted ONNX model path")
    args = parser.parse_args()
    try:
        result = validate_gpu_runtime(args.model)
    except GpuPreflightError as exc:
        LOGGER.error("GPU preflight rejected: %s", str(exc))
        return 2
    LOGGER.info("GPU preflight passed: %s MiB total; %s MiB free; CUDA provider active.",
                result["gpu_memory_total_mib"], result["gpu_memory_free_mib"])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
