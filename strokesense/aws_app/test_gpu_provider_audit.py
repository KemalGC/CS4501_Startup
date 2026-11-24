"""Offline regression checks for measured ONNX execution-provider assignments."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from aws_app.gpu_preflight import GpuPreflightError
from aws_app.gpu_provider_audit import audit_cuda_profile


class CudaProfileAuditTests(unittest.TestCase):
    def check(self, events):
        fd, name = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(events, f)
        path = Path(name)
        try:
            return audit_cuda_profile(name)
        finally:
            self.assertFalse(path.exists(), "profiling file must be deleted")

    @staticmethod
    def node(provider, op):
        return {"cat": "Node", "name": "operator_kernel_time",
                "args": {"provider": provider, "op_name": op}}

    def test_cuda_convolution_with_cpu_shape_ops(self):
        evidence = self.check([
            self.node("CPUExecutionProvider", "Shape"),
            self.node("CUDAExecutionProvider", "Conv"),
            self.node("CUDAExecutionProvider", "Relu"),
        ])
        self.assertEqual(evidence, {"cuda_nodes": 2, "cuda_conv_nodes": 1,
                                    "cpu_structural_nodes": 1})

    def test_cpu_only_and_cpu_convolution_fail_closed(self):
        for events, reason in (
            ([self.node("CPUExecutionProvider", "Shape")], "cuda_kernels_not_verified"),
            ([self.node("CPUExecutionProvider", "Conv"),
              self.node("CUDAExecutionProvider", "Conv")], "cuda_cpu_compute_fallback"),
            ([self.node("CUDAExecutionProvider", "Shape")], "cuda_kernels_not_verified"),
            ([self.node("CUDAExecutionProvider", "Conv"),
              self.node("OtherExecutionProvider", "Shape")], "unexpected_execution_provider"),
        ):
            with self.subTest(reason=reason), self.assertRaises(GpuPreflightError) as error:
                self.check(events)
            self.assertEqual(str(error.exception), reason)
            if reason == "cuda_cpu_compute_fallback":
                self.assertEqual(error.exception.diagnostics["cpu_ops"], ["Conv"])

    def test_missing_or_invalid_profiles_rejected(self):
        with self.assertRaisesRegex(GpuPreflightError, "cuda_profile_missing"):
            audit_cuda_profile("")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            file.write("{}")
            path = file.name
        try:
            with self.assertRaisesRegex(GpuPreflightError, "cuda_profile_invalid"):
                audit_cuda_profile(path)
        finally:
            self.assertFalse(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
