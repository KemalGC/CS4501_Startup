"""Fail-closed ONNX/CUDA readiness check for a FUTURE GPU worker image.

Running this manually never launches AWS compute, schedules a GPU job, or
updates any paid credit. Tests inject fake dependencies on CPU-only hosts.
The real GPU worker and billing adapter have NOT been implemented.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import time
from pathlib import Path
import subprocess
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
GPU_PROVIDER = "CUDAExecutionProvider"
GPU_MIN_TOTAL_MIB = 2800  # The target g6f.large exposes approximately 3 GiB.
GPU_MIN_FREE_MIB = 1800


class GpuPreflightError(RuntimeError):
    """Fixed diagnostic categories; no user media paths in error details."""


WARMUP_RUNS = 3
TIMED_RUNS = 20


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def _synthetic_input(session: Any, np: Any) -> tuple[str, Any]:
    """All-zero tensor matching the model's fixed input; never user media."""
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise GpuPreflightError("unexpected_model_inputs")
    dims = list(inputs[0].shape)
    shape = [1 if i == 0 and not isinstance(d, int) else d for i, d in enumerate(dims)]
    if len(shape) != 4 or not all(isinstance(d, int) and d > 0 for d in shape):
        raise GpuPreflightError("unsupported_model_input_shape")
    return inputs[0].name, np.zeros(shape, dtype=np.float32)


def _device_memory(run: Callable[..., Any] = subprocess.run, *, enforce_minimums: bool = True) -> tuple[int, int]:
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
    if free > total or (enforce_minimums and (total < GPU_MIN_TOTAL_MIB or free < GPU_MIN_FREE_MIB)):
        raise GpuPreflightError("insufficient_gpu_memory")
    return total, free


def _gpu_identity(run: Callable[..., Any] = subprocess.run) -> dict[str, str]:
    """Evidence only (name/driver/vGPU product); never fails the preflight."""
    try:
        result = run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                     capture_output=True, text=True, timeout=8, check=False)
        fields = [v.strip() for v in result.stdout.strip().splitlines()[0].split(",")]
        if result.returncode == 0 and len(fields) == 2:
            return {"gpu_name": fields[0][:80], "nvidia_driver_version": fields[1][:40]}
    except Exception:  # noqa: BLE001 - diagnostic best effort
        pass
    return {"gpu_name": "unknown", "nvidia_driver_version": "unknown"}


def validate_gpu_runtime(model: Path, *, run: Callable[..., Any] = subprocess.run,
                         import_module: Callable[[str], Any] = importlib.import_module,
                         clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Prove CUDA is the first active ONNX provider for the specified model."""
    if model.suffix.lower() != ".onnx" or not model.is_file():
        raise GpuPreflightError("model_not_found")
    total, free = _device_memory(run)
    try:
        ort = import_module("onnxruntime")
        available = ort.get_available_providers()
        if GPU_PROVIDER not in available:
            raise GpuPreflightError("cuda_provider_unavailable")
        options = ort.SessionOptions()
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        session = ort.InferenceSession(str(model), options, providers=[GPU_PROVIDER])
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
    # Execute real CUDA kernels (cuDNN conv etc.) on a synthetic tensor: a
    # provider list alone does not prove the GPU can run the model.
    try:
        np = import_module("numpy")
        name, tensor = _synthetic_input(session, np)
        latencies_ms: list[float] = []
        outputs: Any = None
        for i in range(WARMUP_RUNS + TIMED_RUNS):
            started = clock()
            outputs = session.run(None, {name: tensor})
            if i >= WARMUP_RUNS:
                latencies_ms.append((clock() - started) * 1000.0)
        if not outputs or not all(getattr(o, "size", 0) > 0 for o in outputs):
            raise GpuPreflightError("empty_inference_output")
        if not all(bool(np.all(np.isfinite(o))) for o in outputs):
            raise GpuPreflightError("non_finite_inference_output")
        if session.get_providers()[0] != GPU_PROVIDER:
            raise GpuPreflightError("cuda_provider_not_active")
    except GpuPreflightError:
        raise
    except Exception as exc:
        raise GpuPreflightError("cuda_inference_failed") from exc
    _, free_after = _device_memory(run, enforce_minimums=False)
    return {**_gpu_identity(run), "provider": GPU_PROVIDER,
            "active_providers": list(session.get_providers()),
            "cpu_ep_fallback_disabled": True, "outputs_finite": True,
            "warmup_runs": WARMUP_RUNS, "gpu_memory_total_mib": total,
            "gpu_memory_free_mib": free, "model_loaded": True,
            "onnxruntime_version": str(getattr(ort, "__version__", "unknown")),
            "input_shape": [int(d) for d in tensor.shape],
            "output_shapes": [[int(d) for d in getattr(o, "shape", ())] for o in outputs],
            "inference_runs": len(latencies_ms),
            "latency_ms_p50": round(_percentile(latencies_ms, 50), 3),
            "latency_ms_p95": round(_percentile(latencies_ms, 95), 3),
            "latency_ms_max": round(max(latencies_ms), 3),
            "gpu_memory_used_after_inference_mib": total - free_after}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GPU readiness; does not run paid inference.")
    parser.add_argument("--model", required=True, type=Path, help="Locally mounted ONNX model path")
    args = parser.parse_args()
    try:
        # Re-verify the packaged weights at runtime (size + SHA256 pin).
        from aws_app.gpu_model_integrity import BASELINE_MODEL_SHA256, verify_gpu_model
        try:
            verify_gpu_model(args.model)
        except Exception as exc:  # WorkerError or OSError; fixed category only
            raise GpuPreflightError("model_integrity_failed") from exc
        result = validate_gpu_runtime(args.model)
        result["model_sha256_verified"] = BASELINE_MODEL_SHA256
    except GpuPreflightError as exc:
        LOGGER.error("GPU preflight rejected: %s", str(exc))
        return 2
    LOGGER.info("GPU preflight passed: %s MiB total; %s MiB free; CUDA provider active.",
                result["gpu_memory_total_mib"], result["gpu_memory_free_mib"])
    # One machine-readable line for CloudWatch evidence (no media, no paths).
    print("STROKESENSE_GPU_PREFLIGHT " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
