"""Fail-closed ONNX/CUDA readiness check for the GPU worker image.

Running this manually never launches AWS compute, schedules a GPU job, or
updates any paid credit. Tests inject fake dependencies on CPU-only hosts.
Synthetic model inference does not validate the video or billing pipeline.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import time
from pathlib import Path
import subprocess
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
GPU_PROVIDER = "CUDAExecutionProvider"
GPU_MIN_TOTAL_MIB = 2800  # The target g6f.xlarge exposes approximately 3 GiB.
GPU_MIN_FREE_MIB = 1800


class GpuPreflightError(RuntimeError):
    """Fixed categories with bounded diagnostic context kept out of str(exc)."""

    def __init__(self, category: str, *, stage: str | None = None,
                 diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(category)
        self.stage = stage
        self.diagnostics = diagnostics or {}


WARMUP_RUNS = 3
TIMED_RUNS = 20


def _diagnostic_text(value: Any, limit: int = 1024) -> str:
    """Bound runtime details and redact common credential/path patterns."""
    try:
        text = str(value)
    except Exception:  # Diagnostic conversion must not hide the real failure.
        return "<exception detail unavailable>"
    # Bound work as well as output; an exception must not dump an entire model.
    text = text[:16384]
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"(?i)\b(?:https?|s3)://[^\s<>\"']+", "<uri>", text)
    text = re.sub(r"(?i)\b(?:authorization\s*[:=]\s*)?(?:bearer|basic)\s+\S+", "<credential>", text)
    text = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "<credential>", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<credential>", text)
    text = re.sub(
        r"(?i)\b([A-Za-z0-9_-]*(?:password|passwd|secret|token|api[_-]?key)[A-Za-z0-9_-]*|aws_access_key_id)['\"]?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1=<credential>", text,
    )

    def redact_path(match: re.Match[str]) -> str:
        name = match.group(0).replace("\\", "/").rsplit("/", 1)[-1]
        # Library basenames identify linker failures; other filenames can be
        # user-controlled and are unnecessary for this fixed model preflight.
        return "<path>/" + name if re.fullmatch(r"lib[A-Za-z0-9_.+-]+\.so(?:\.\d+)*", name) else "<path>"

    text = re.sub(r"(?<![\w.])(?:[A-Za-z]:[\\/]|/)[^\s<>\"'()\[\]:,;]*", redact_path, text)
    text = " ".join(text.split()).encode("ascii", errors="replace").decode("ascii")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _failure_record(error: GpuPreflightError, default_stage: str,
                    verified_model_sha256: str | None = None) -> dict[str, Any]:
    category = str(error)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", category):
        category = "preflight_unexpected_failure"
    record: dict[str, Any] = {
        "error": category, "stage": _diagnostic_text(error.stage or default_stage, 80),
        "exception_type": type(error).__name__[:80], "causes": [],
    }
    seen = {id(error)}
    cause = error.__cause__
    while cause is not None and id(cause) not in seen and len(record["causes"]) < 3:
        seen.add(id(cause))
        record["causes"].append({"exception_type": type(cause).__name__[:80],
                                  "message": _diagnostic_text(cause)})
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    context = error.diagnostics
    for key in ("onnxruntime_version", "gpu_name", "nvidia_driver_version"):
        if key in context:
            record[key] = _diagnostic_text(context[key], 80)
    for key in ("gpu_memory_total_mib", "gpu_memory_free_mib"):
        if type(context.get(key)) is int and 0 <= context[key] <= 1_000_000:
            record[key] = context[key]
    if isinstance(context.get("available_providers"), (list, tuple)):
        record["available_providers"] = [_diagnostic_text(v, 80) for v in context["available_providers"][:8]]
    if verified_model_sha256 and re.fullmatch(r"[a-f0-9]{64}", verified_model_sha256):
        record["model_sha256_verified"] = verified_model_sha256
    return record


def _report_failure(error: GpuPreflightError, default_stage: str,
                    verified_model_sha256: str | None = None) -> None:
    """The failure marker is distinct from the success-only evidence marker."""
    try:
        record = _failure_record(error, default_stage, verified_model_sha256)
    except Exception:  # Diagnostics can fail, but the original preflight still fails closed.
        record = {"error": "preflight_unexpected_failure", "stage": default_stage,
                  "diagnostics_unavailable": True}
    LOGGER.error("GPU preflight rejected: %s", record["error"])
    try:
        print("STROKESENSE_GPU_PREFLIGHT_FAILURE " + json.dumps(record, sort_keys=True), flush=True)
    except (OSError, ValueError):
        pass  # Closed output must not turn this failure into a different result.


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


def _runtime_failure_context(ort: Any, available: Any, total: int, free: int,
                             run: Callable[..., Any]) -> dict[str, Any]:
    """Collect only named diagnostic fields, and only after a runtime failure."""
    context: dict[str, Any] = {"gpu_memory_total_mib": total, "gpu_memory_free_mib": free}
    try:
        context.update(_gpu_identity(run))
        context["onnxruntime_version"] = getattr(ort, "__version__", "unknown")
        if isinstance(available, (list, tuple)):
            context["available_providers"] = available[:8]
    except Exception:  # noqa: BLE001 - keep the original exception as the cause
        pass
    return context


def validate_gpu_runtime(model: Path, *, run: Callable[..., Any] = subprocess.run,
                         import_module: Callable[[str], Any] = importlib.import_module,
                         clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Prove CUDA is the first active ONNX provider for the specified model."""
    if model.suffix.lower() != ".onnx" or not model.is_file():
        raise GpuPreflightError("model_not_found", stage="model_file")
    try:
        total, free = _device_memory(run)
    except GpuPreflightError as exc:
        exc.stage = "device_memory"
        raise
    ort: Any = None
    available: Any = None
    stage = "onnxruntime_import"
    try:
        ort = import_module("onnxruntime")
        stage = "provider_discovery"
        available = ort.get_available_providers()
        if GPU_PROVIDER not in available:
            raise GpuPreflightError("cuda_provider_unavailable")
        stage = "session_options"
        options = ort.SessionOptions()
        # ORT legitimately uses CPU for some metadata/shape nodes. Disabling
        # every CPU graph node prevents this pinned model from initializing.
        # Profiling below must instead prove real CUDA kernels executed.
        options.enable_profiling = True
        stage = "session_creation"
        session = ort.InferenceSession(str(model), options, providers=[GPU_PROVIDER])
        stage = "provider_activation"
        active = session.get_providers()
        if not isinstance(active, list) or not active or active[0] != GPU_PROVIDER:
            raise GpuPreflightError("cuda_provider_not_active")
        # Do not silently allow an unexpected CPU-only session.
        stage = "fallback_configuration"
        if callable(getattr(session, "disable_fallback", None)):
            session.disable_fallback()
    except GpuPreflightError as exc:
        exc.stage = stage
        exc.diagnostics = _runtime_failure_context(ort, available, total, free, run)
        raise
    except Exception as exc:
        raise GpuPreflightError("cuda_session_initialization_failed", stage=stage,
                                diagnostics=_runtime_failure_context(ort, available, total, free, run)) from exc
    # Execute real CUDA kernels (cuDNN conv etc.) on a synthetic tensor: a
    # provider list alone does not prove the GPU can run the model.
    try:
        stage = "numpy_import"
        np = import_module("numpy")
        stage = "synthetic_input"
        name, tensor = _synthetic_input(session, np)
        latencies_ms: list[float] = []
        outputs: Any = None
        for i in range(WARMUP_RUNS + TIMED_RUNS):
            stage = "synthetic_inference"
            started = clock()
            outputs = session.run(None, {name: tensor})
            if i >= WARMUP_RUNS:
                latencies_ms.append((clock() - started) * 1000.0)
            # A later good result must not hide an invalid warm-up or timed
            # result. Validate outside the timed region on every invocation.
            stage = "inference_output_validation"
            if not outputs or not all(getattr(o, "size", 0) > 0 for o in outputs):
                raise GpuPreflightError("empty_inference_output")
            if not all(bool(np.all(np.isfinite(o))) for o in outputs):
                raise GpuPreflightError("non_finite_inference_output")
        stage = "provider_audit"
        from aws_app.gpu_provider_audit import audit_cuda_profile
        audit = audit_cuda_profile(session.end_profiling())
        stage = "provider_recheck"
        if session.get_providers()[0] != GPU_PROVIDER:
            raise GpuPreflightError("cuda_provider_not_active")
    except GpuPreflightError as exc:
        exc.stage = stage
        exc.diagnostics = _runtime_failure_context(ort, available, total, free, run)
        raise
    except Exception as exc:
        raise GpuPreflightError("cuda_inference_failed", stage=stage,
                                diagnostics=_runtime_failure_context(ort, available, total, free, run)) from exc
    _, free_after = _device_memory(run, enforce_minimums=False)
    return {**_gpu_identity(run), "provider": GPU_PROVIDER,
            "active_providers": list(session.get_providers()),
            "cpu_ep_fallback_disabled": False, "cuda_node_execution_verified": True,
            "provider_audit": audit, "outputs_finite": True,
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
    stage = "model_integrity"
    verified_model_sha256 = None
    try:
        # Re-verify the packaged weights at runtime (size + SHA256 pin).
        from aws_app.gpu_model_integrity import BASELINE_MODEL_SHA256, verify_gpu_model
        try:
            verify_gpu_model(args.model)
        except Exception as exc:  # WorkerError or OSError; paths excluded from diagnostics
            raise GpuPreflightError("model_integrity_failed", stage=stage) from exc
        verified_model_sha256 = BASELINE_MODEL_SHA256
        stage = "gpu_runtime"
        result = validate_gpu_runtime(args.model)
        result["model_sha256_verified"] = BASELINE_MODEL_SHA256
    except GpuPreflightError as exc:
        _report_failure(exc, stage, verified_model_sha256)
        return 2
    except Exception as exc:
        failure = GpuPreflightError("preflight_unexpected_failure", stage=stage)
        failure.__cause__ = exc
        _report_failure(failure, stage, verified_model_sha256)
        return 2
    LOGGER.info("GPU preflight passed: %s MiB total; %s MiB free; CUDA provider active.",
                result["gpu_memory_total_mib"], result["gpu_memory_free_mib"])
    # One machine-readable line for CloudWatch evidence (no media, no paths).
    print("STROKESENSE_GPU_PREFLIGHT " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
