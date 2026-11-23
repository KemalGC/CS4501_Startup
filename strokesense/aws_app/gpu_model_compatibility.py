"""Build-time model/runtime compatibility check; this is not CUDA validation.

The GPU wheel also includes a CPU provider. Loading the pinned model with that
provider catches ONNX IR/opset and graph errors before publishing an image or
starting a billable GPU host. Runtime GPU preflight remains a separate check.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
from typing import Any

from .gpu_model_integrity import BASELINE_MODEL_SHA256, verify_gpu_model


# Keep provider handles alive for the process lifetime, including after the
# model compatibility check returns to another build-time validation caller.
_CUDA_LIBRARY_HANDLES: list[Any] = []


def _check_cuda_linkage(ort: Any) -> dict[str, Any]:
    from onnxruntime.capi.build_and_package_info import cuda_version

    # Verify the exact wheel, rather than inferring its CUDA build from a
    # generic version-family table. The reviewed cp310 Linux 1.21.1 wheel
    # records CUDA 12.2; the retained NVIDIA base provides CUDA 12.6.3.
    if ort.__version__ != "1.21.1" or cuda_version != "12.2":
        raise RuntimeError("unreviewed_onnxruntime_cuda_build")
    capi = Path(ort.__file__).resolve().parent / "capi"
    # CUDA's provider imports Provider_GetHost from the shared provider shim.
    # Resolve symbols now, but never call GetProvider or initialize a device.
    shared = ctypes.CDLL(str(capi / "libonnxruntime_providers_shared.so"), mode=os.RTLD_GLOBAL | os.RTLD_NOW)
    cuda = ctypes.CDLL(str(capi / "libonnxruntime_providers_cuda.so"), mode=os.RTLD_NOW | os.RTLD_LOCAL)
    _CUDA_LIBRARY_HANDLES.extend((shared, cuda))
    return {"cuda_wheel_build_version": cuda_version, "cuda_provider_libraries_loaded": True}


def validate_model_compatibility(model: Path, *, check_cuda_libraries: bool = False) -> dict[str, Any]:
    verify_gpu_model(model)
    import numpy as np
    import onnxruntime as ort

    linkage = _check_cuda_linkage(ort) if check_cuda_libraries else {}
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
    parser = argparse.ArgumentParser(description="Check pinned ONNX model compatibility on CPU; does not verify CUDA.")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--check-cuda-libraries", action="store_true", help="Also resolve the reviewed Linux CUDA provider's shared libraries; requires the CUDA image, not a GPU.")
    args = parser.parse_args()
    result = validate_model_compatibility(args.model, check_cuda_libraries=args.check_cuda_libraries)
    print("STROKESENSE_GPU_MODEL_COMPATIBILITY " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
