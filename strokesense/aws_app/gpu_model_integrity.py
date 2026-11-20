"""Pin the first paid CUDA worker to the verified baseline YOLO ONNX file."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .worker import WorkerError

# Must match strokesense.pose.MODEL_SHA256; do not fetch weights at runtime.
BASELINE_MODEL_SHA256 = "93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408"
BASELINE_MODEL_BYTES = 11853451


def verify_gpu_model(model: Path) -> None:
    if model.is_symlink() or not model.is_file() or model.stat().st_size != BASELINE_MODEL_BYTES:
        raise WorkerError("invalid_gpu_model")
    digest = hashlib.sha256()
    with model.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != BASELINE_MODEL_SHA256:
        raise WorkerError("gpu_model_integrity_failed")
