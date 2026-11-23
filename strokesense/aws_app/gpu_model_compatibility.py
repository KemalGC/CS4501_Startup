"""Build-time model/runtime compatibility check; this is not CUDA validation.

The GPU wheel also includes a CPU provider. Loading the pinned model with that
provider catches ONNX IR/opset and graph errors before publishing an image or
starting a billable GPU host. Runtime GPU preflight remains a separate check.
"""
from __future__ import annotations

import argparse
import contextlib
import faulthandler
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .gpu_model_integrity import BASELINE_MODEL_SHA256, verify_gpu_model


def _check_cuda_linkage(ort: Any) -> dict[str, Any]:
    from onnxruntime.capi.build_and_package_info import cuda_version

    # Verify the exact wheel, rather than inferring its CUDA build from a
    # generic version-family table. The reviewed cp310 Linux 1.21.1 wheel
    # records CUDA 12.2; the retained NVIDIA base provides CUDA 12.6.3.
    if ort.__version__ != "1.21.1" or cuda_version != "12.2":
        raise RuntimeError("unreviewed_onnxruntime_cuda_build")
    # Use the public ORT API to load NVIDIA dependency libraries. Loading the
    # execution-provider .so directly is invalid: its global constructors
    # dereference the ProviderHost installed by ORT's private provider bridge.
    # preload_dlls reports failures through stdout, so do not ignore its text.
    print("STROKESENSE_GPU_BUILD_STAGE cuda_dependency_preload", flush=True)
    preload_output = io.StringIO()
    with contextlib.redirect_stdout(preload_output):
        ort.preload_dlls(cuda=True, cudnn=True, msvc=False)
    if preload_output.getvalue().strip():
        raise RuntimeError("cuda_dependency_preload_failed: " + preload_output.getvalue().strip()[:2000])

    # glibc ldd -r uses loader tracing and relocation checks, without running
    # the provider's constructors. Supply the shared bridge for Provider_GetHost
    # symbol resolution in this child only; never call private provider APIs.
    capi = Path(ort.__file__).resolve().parent / "capi"
    child_environment = dict(os.environ)
    child_environment["LD_PRELOAD"] = str(capi / "libonnxruntime_providers_shared.so")
    child_environment["LC_ALL"] = "C"
    print("STROKESENSE_GPU_BUILD_STAGE cuda_provider_relocations", flush=True)
    checked = subprocess.run(
        ["ldd", "-r", str(capi / "libonnxruntime_providers_cuda.so")],
        env=child_environment, capture_output=True, text=True, timeout=30,
    )
    details = checked.stdout + checked.stderr
    failure_markers = ("not found", "undefined symbol", "symbol lookup error", "cannot be preloaded", "error while loading shared libraries")
    if checked.returncode != 0 or any(marker in details for marker in failure_markers):
        raise RuntimeError("cuda_provider_linkage_failed: " + details.strip()[:4000])
    return {
        "cuda_wheel_build_version": cuda_version,
        "cuda_dependency_libraries_loaded": True,
        "cuda_provider_relocations_verified": True,
    }


def validate_model_compatibility(model: Path, *, check_cuda_libraries: bool = False) -> dict[str, Any]:
    verify_gpu_model(model)
    import numpy as np
    import onnxruntime as ort

    linkage = _check_cuda_linkage(ort) if check_cuda_libraries else {}
    print("STROKESENSE_GPU_BUILD_STAGE cpu_model_load", flush=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
    session.disable_fallback()
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("compatibility_check_requires_explicit_cpu_provider")
    inputs = session.get_inputs()
    if (len(inputs) != 1 or inputs[0].type != "tensor(float)"
            or list(inputs[0].shape) != [1, 3, 640, 640]):
        raise RuntimeError("pinned_model_input_contract_changed")
    print("STROKESENSE_GPU_BUILD_STAGE cpu_model_inference", flush=True)
    outputs = session.run(None, {inputs[0].name: np.zeros((1, 3, 640, 640), dtype=np.float32)})
    if (len(outputs) != 1 or outputs[0].shape != (1, 56, 8400)
            or outputs[0].dtype != np.float32 or not bool(np.all(np.isfinite(outputs[0])))):
        raise RuntimeError("pinned_model_output_contract_failed")
    return {
        **linkage,
        "check": "cpu_model_compatibility",
        "model_sha256_verified": BASELINE_MODEL_SHA256,
        "onnxruntime_version": ort.__version__,
        "provider": "CPUExecutionProvider",
        "input_shape": list(inputs[0].shape),
        "output_shapes": [list(output.shape) for output in outputs],
        "outputs_finite": True,
        "gpu_inference_verified": False,
    }


def main() -> int:
    faulthandler.enable()
    parser = argparse.ArgumentParser(description="Check pinned ONNX model compatibility on CPU; does not verify CUDA.")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--check-cuda-libraries", action="store_true", help="Also resolve the reviewed Linux CUDA provider's shared libraries; requires the CUDA image, not a GPU.")
    args = parser.parse_args()
    result = validate_model_compatibility(args.model, check_cuda_libraries=args.check_cuda_libraries)
    print("STROKESENSE_GPU_MODEL_COMPATIBILITY " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
