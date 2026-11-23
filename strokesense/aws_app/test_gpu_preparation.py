"""Paid membership and GPU preflight preparation, no hardware or AWS calls."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from aws_app.core import ApiError, AwsBackend, Settings, _item
from aws_app.gpu_preflight import GpuPreflightError, WARMUP_RUNS, _failure_record, main, validate_gpu_runtime
from aws_app.paid_access import evaluate_paid_membership, require_paid_membership
from aws_app.test_backend import FakeS3, FakeBatch, MemoryDynamo


class PaidGpuPreparationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.ddb, self.s3, self.batch = MemoryDynamo(), FakeS3(), FakeBatch()
        self.body = {"content_type": "video/mp4", "size_bytes": 100_000_000, "tier": "paid"}

    def svc(self, **overrides):
        settings = dict(batch_queue="free-cpu-queue", batch_definition="cpu-def",
                        paid_billing_enabled=True, paid_gpu_enabled=True, gpu_dispatch_ready=True)
        settings.update(overrides)
        return AwsBackend(Settings("media", "users", "jobs", **settings),
                          self.ddb, self.s3, self.batch, clock=lambda: self.now)

    def grant_future_test_membership(self, credits=2, expires=3600):
        self.svc()._account("member")
        self.ddb.accounts["member"].update(
            paid_membership_status="active",
            paid_membership_expires_at=self.now + expires,
            paid_credits_available=credits,
        )

    def test_paid_flags_are_independently_required_and_disabled_by_default(self):
        default = AwsBackend(Settings("media", "users", "jobs", paid_billing_enabled=False),
                             self.ddb, self.s3, self.batch, clock=lambda: self.now)
        with self.assertRaises(ApiError) as error:
            default.start_upload("member", self.body)
        self.assertEqual(error.exception.code, "billing_not_configured")
        for kwargs in [{"paid_gpu_enabled": False},
                       {"gpu_dispatch_ready": False},
                       {"paid_billing_enabled": False}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ApiError):
                self.svc(**kwargs).start_upload("member", self.body)
        self.assertEqual(self.ddb.jobs, {})

    def test_active_membership_and_credits_are_checked_on_server(self):
        service = self.svc()
        with self.assertRaises(ApiError) as error:
            service.start_upload("member", self.body)
        self.assertEqual(error.exception.code, "paid_membership_required")
        self.grant_future_test_membership()
        result = service.start_upload("member", self.body)
        self.assertEqual(result["tier"], "paid")
        self.assertEqual(self.ddb.accounts["member"]["paid_credits_reserved"], 1)
        # The atomic DynamoDB transaction condition must also re-check expiry.
        transactions = [tx for tx in self.ddb.transactions if
                        any("Put" in action for action in tx)]
        reserve = transactions[-1][0]["Update"]
        self.assertIn("paid_membership_expires_at > :now", reserve["ConditionExpression"])
        self.assertIn("paid_membership_status = :member", reserve["ConditionExpression"])
        self.assertEqual(reserve["ExpressionAttributeValues"][":member"], {"S": "active"})
        self.assertEqual(reserve["ExpressionAttributeValues"][":now"], {"N": str(self.now)})

    def test_member_cancellation_expiry_and_zero_credits_fail_closed(self):
        for status, delta, credits, expected in [
            ("canceled", 3600, 1, "paid_membership_required"),
            ("active", 0, 1, "paid_membership_required"),
            ("active", -1, 1, "paid_membership_required"),
            ("active", 3600, 0, "paid_credits_exhausted")
        ]:
            with self.subTest(status=status, delta=delta, credits=credits):
                record = {"paid_membership_status": status,
                          "paid_membership_expires_at": self.now + delta,
                          "paid_credits_available": credits}
                with self.assertRaises(ApiError) as error:
                    evaluate_paid_membership(record, self.now)
                self.assertEqual(error.exception.code, expected)
        self.grant_future_test_membership(credits=1, expires=3600)
        service = self.svc()
        self.now += 3600
        with self.assertRaises(ApiError) as error:
            require_paid_membership(service, "member")
        self.assertEqual(error.exception.code, "paid_membership_required")

    def test_atomic_credit_reservation_denies_race_at_membership_expiry(self):
        self.grant_future_test_membership(credits=1, expires=1)
        service = self.svc()
        # A separate owner read was valid, but the transaction executes after expiry.
        account = self.ddb.accounts["member"]
        record = {"job_id": "b" * 32, "user_id": "member", "tier": "paid",
                  "size_bytes": 100_000_000, "status": "uploading",
                  "created_at": "2026-11-20T00:00:00+00:00"}
        self.now += 2
        from aws_app.core import _is_conditional
        with self.assertRaises(Exception) as fail:
            service._quota_transaction(record, "reserve")
        self.assertTrue(_is_conditional(fail.exception))
        self.assertEqual(account["paid_credits_available"], 1)
        self.assertEqual(self.ddb.jobs, {})

    def test_paid_jobs_cannot_submit_to_free_cpu_queue_or_consume_cpu_caps(self):
        self.grant_future_test_membership()
        service = self.svc()
        video = service.start_upload("member", self.body)["video_id"]
        self.ddb.jobs[video]["status"] = "uploaded"
        before = len(self.ddb.transactions)
        self.batch.submit_job = Mock()
        with self.assertRaises(ApiError) as blocked:
            service.submit_analysis("member", {"video_id": video})
        self.assertEqual(blocked.exception.code, "gpu_dispatch_unavailable")
        self.assertEqual(len(self.ddb.transactions), before)
        self.batch.submit_job.assert_not_called()
        self.assertFalse(any(k.startswith("__strokesense_cpu_admissions__/") for k in self.ddb.accounts))


class GpuRuntimePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name) / "yolo11n-pose.onnx"
        self.model.write_bytes(b"local dummy model; ONNX session is mocked")

    @staticmethod
    def nvidia_memory(total=3072, free=2600, code=0):
        return lambda *_args, **_kwargs: SimpleNamespace(
            returncode=code, stdout=f"{total},{free}\n",
        )

    @staticmethod
    def ort(available, active, input_shape=("batch", 3, 640, 640), run=None, profile_events=None):
        """Fake serving as both `onnxruntime` and the `numpy` zeros it needs."""
        def zeros(shape, dtype=None):
            return SimpleNamespace(shape=tuple(shape), dtype=dtype)

        def default_run(_names, feeds):
            (tensor,) = feeds.values()
            assert tensor.shape[0] == 1 and tensor.dtype == "float32"
            return [SimpleNamespace(shape=(1, 56, 8400), size=56 * 8400)]

        def end_profiling():
            handle, path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(profile_events if profile_events is not None else [
                    {"cat": "Node", "name": "Conv_0_kernel_time",
                     "args": {"provider": "CUDAExecutionProvider", "op_name": "Conv"}},
                    {"cat": "Node", "name": "Shape_0_kernel_time",
                     "args": {"provider": "CPUExecutionProvider", "op_name": "Shape"}}
                ], stream)
            return path

        return SimpleNamespace(
            __version__="1.20.2", float32="float32", zeros=zeros,
            isfinite=lambda o: o, all=lambda o: getattr(o, "finite", True),
            get_available_providers=lambda: available,
            SessionOptions=lambda: SimpleNamespace(add_session_config_entry=lambda *_args: None),
            InferenceSession=lambda *args, **kwargs: SimpleNamespace(
                get_providers=lambda: active,
                disable_fallback=lambda: None,
                get_inputs=lambda: [SimpleNamespace(name="images", shape=list(input_shape))],
                run=run or default_run,
                end_profiling=end_profiling,
            ),
        )

    def test_preflight_executes_cuda_inference_and_reports_metrics(self):
        calls = []
        ort = self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"],
                       run=lambda names, feeds: calls.append(feeds) or
                       [SimpleNamespace(shape=(1, 56, 8400), size=470400)])
        ticks = iter(float(i) / 1000 for i in range(1000))
        memory = iter(["3072,2600\n", "3072,2100\n"])

        def run(cmd, *_a, **_k):
            if "--query-gpu=name,driver_version" in cmd:
                return SimpleNamespace(returncode=0, stdout="NVIDIA L4-3Q, 570.172.08\n")
            return SimpleNamespace(returncode=0, stdout=next(memory))
        result = validate_gpu_runtime(self.model, run=run, import_module=lambda _n: ort,
                                      clock=lambda: next(ticks))
        self.assertEqual(result["gpu_name"], "NVIDIA L4-3Q")
        self.assertEqual(result["nvidia_driver_version"], "570.172.08")
        self.assertEqual(result["active_providers"], ["CUDAExecutionProvider"])
        self.assertTrue(result["outputs_finite"])
        self.assertTrue(result["cuda_node_execution_verified"])
        self.assertEqual(result["provider_audit"]["cuda_conv_nodes"], 1)
        self.assertEqual(result["warmup_runs"], 3)
        self.assertEqual(len(calls), 23)  # 3 warm-up + 20 timed real session.run calls
        self.assertEqual(result["inference_runs"], 20)
        self.assertEqual(result["input_shape"], [1, 3, 640, 640])
        self.assertEqual(result["output_shapes"], [[1, 56, 8400]])
        self.assertEqual(result["latency_ms_p50"], 1.0)
        self.assertEqual(result["gpu_memory_used_after_inference_mib"], 972)
        self.assertEqual(result["onnxruntime_version"], "1.20.2")

    def test_inference_failures_fail_closed(self):
        def boom(*_args):
            raise RuntimeError("CUDNN_STATUS_EXECUTION_FAILED")
        cases = [
            (self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"], run=boom), "cuda_inference_failed"),
            (self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"], run=lambda *_a: []), "empty_inference_output"),
            (self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"],
                      run=lambda *_a: [SimpleNamespace(shape=(1, 2), size=2, finite=False)]),
             "non_finite_inference_output"),
            (self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"], input_shape=(1, 3, "h", "w")),
             "unsupported_model_input_shape"),
        ]
        for ort, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(GpuPreflightError) as caught:
                validate_gpu_runtime(self.model, run=self.nvidia_memory(), import_module=lambda _n, o=ort: o)
            self.assertEqual(str(caught.exception), expected)

    def test_cuda_model_session_and_vram_must_be_real(self):
        ort = self.ort(["CUDAExecutionProvider", "CPUExecutionProvider"],
                       ["CUDAExecutionProvider", "CPUExecutionProvider"])
        result = validate_gpu_runtime(
            self.model, run=self.nvidia_memory(),
            import_module=lambda _name: ort,
        )
        self.assertEqual(result["provider"], "CUDAExecutionProvider")
        self.assertEqual(result["gpu_memory_total_mib"], 3072)

    def test_invalid_early_inference_is_not_hidden_by_later_valid_outputs(self):
        good = [SimpleNamespace(shape=(1, 56, 8400), size=470400)]
        invalid_outputs = [
            ([], "empty_inference_output"),
            ([SimpleNamespace(shape=(0,), size=0)], "empty_inference_output"),
            ([SimpleNamespace(shape=(1, 56, 8400), size=470400, finite=False)],
             "non_finite_inference_output"),
        ]
        for bad_at in (0, WARMUP_RUNS, WARMUP_RUNS + 5):
            for bad, expected in invalid_outputs:
                with self.subTest(bad_at=bad_at, expected=expected):
                    call_count = 0

                    def inference(*_args):
                        nonlocal call_count
                        result = bad if call_count == bad_at else good
                        call_count += 1
                        return result

                    ort = self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"],
                                   run=inference)
                    with self.assertRaises(GpuPreflightError) as caught:
                        validate_gpu_runtime(self.model, run=self.nvidia_memory(),
                                             import_module=lambda _name: ort)
                    self.assertEqual(str(caught.exception), expected)
                    self.assertEqual(call_count, bad_at + 1)

    def test_cpu_fallback_and_absent_cuda_are_rejected(self):
        for available, active, expected in [
            (["CPUExecutionProvider"], ["CPUExecutionProvider"], "cuda_provider_unavailable"),
            (["CUDAExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"],
             "cuda_provider_not_active"),
        ]:
            with self.subTest(active=active), self.assertRaises(GpuPreflightError) as caught:
                validate_gpu_runtime(self.model, run=self.nvidia_memory(),
                                     import_module=lambda _name: self.ort(available, active))
            self.assertEqual(str(caught.exception), expected)

    def test_underpowered_gpu_or_missing_driver_fails_closed(self):
        for run in [self.nvidia_memory(total=1024), self.nvidia_memory(free=300),
                    self.nvidia_memory(code=1)]:
            with self.subTest(run=run), self.assertRaises(GpuPreflightError):
                validate_gpu_runtime(self.model, run=run,
                                     import_module=lambda _name: self.ort([], []))
        with self.assertRaises(GpuPreflightError) as err:
            validate_gpu_runtime(Path(self.temp.name) / "missing.onnx", run=self.nvidia_memory())
        self.assertEqual(str(err.exception), "model_not_found")

    def failed_main_record(self, failure):
        output = io.StringIO()
        with patch("sys.argv", ["gpu_preflight", "--model", str(self.model)]), \
             patch("aws_app.gpu_model_integrity.verify_gpu_model"), \
             patch("aws_app.gpu_preflight.validate_gpu_runtime", side_effect=failure), \
             redirect_stdout(output), self.assertLogs("aws_app.gpu_preflight", level="ERROR"):
            self.assertEqual(main(), 2)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("STROKESENSE_GPU_PREFLIGHT_FAILURE "))
        self.assertFalse(lines[0].startswith("STROKESENSE_GPU_PREFLIGHT "))
        return json.loads(lines[0].split(" ", 1)[1])

    def test_unsupported_opset_cause_is_reported_without_allowing_cpu_fallback(self):
        class UnsupportedOpset(RuntimeError):
            pass

        ort = self.ort(["CUDAExecutionProvider", "CPUExecutionProvider"], ["CUDAExecutionProvider"])
        options = SimpleNamespace(add_session_config_entry=Mock())
        ort.SessionOptions = lambda: options
        ort.InferenceSession = Mock(side_effect=UnsupportedOpset(
            f"Load model from {self.model} failed: Opset 22 is under development; "
            "current official support is till opset 21."
        ))
        with self.assertRaises(GpuPreflightError) as caught:
            validate_gpu_runtime(self.model, run=self.nvidia_memory(), import_module=lambda _n: ort)
        self.assertEqual(str(caught.exception), "cuda_session_initialization_failed")
        options.add_session_config_entry.assert_not_called()
        self.assertTrue(options.enable_profiling)
        ort.InferenceSession.assert_called_once_with(str(self.model), options, providers=["CUDAExecutionProvider"])
        record = self.failed_main_record(caught.exception)
        self.assertEqual(record["stage"], "session_creation")
        self.assertEqual(record["causes"][0]["exception_type"], "UnsupportedOpset")
        self.assertIn("Opset 22", record["causes"][0]["message"])
        self.assertIn("opset 21", record["causes"][0]["message"])
        self.assertNotIn(str(self.model), json.dumps(record))
        self.assertEqual(record["onnxruntime_version"], "1.20.2")
        self.assertEqual(record["available_providers"], ["CUDAExecutionProvider", "CPUExecutionProvider"])
        self.assertEqual(record["gpu_memory_total_mib"], 3072)
        self.assertEqual(record["model_sha256_verified"], "93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408")

    def test_import_and_inference_failures_keep_their_distinct_stage_and_cause(self):
        def missing_package(_name):
            raise ImportError("libcudnn.so.9: cannot open shared object file")

        with self.assertRaises(GpuPreflightError) as imported:
            validate_gpu_runtime(self.model, run=self.nvidia_memory(), import_module=missing_package)
        record = self.failed_main_record(imported.exception)
        self.assertEqual(record["stage"], "onnxruntime_import")
        self.assertEqual(record["causes"][0]["exception_type"], "ImportError")
        self.assertIn("libcudnn.so.9", record["causes"][0]["message"])

        ort = self.ort(["CUDAExecutionProvider"], ["CUDAExecutionProvider"],
                       run=Mock(side_effect=RuntimeError("CUDNN_STATUS_EXECUTION_FAILED")))
        with self.assertRaises(GpuPreflightError) as inference:
            validate_gpu_runtime(self.model, run=self.nvidia_memory(), import_module=lambda _n: ort)
        record = self.failed_main_record(inference.exception)
        self.assertEqual(record["error"], "cuda_inference_failed")
        self.assertEqual(record["stage"], "synthetic_inference")
        self.assertIn("CUDNN_STATUS_EXECUTION_FAILED", record["causes"][0]["message"])

    def test_failure_details_are_bounded_and_redact_paths_credentials_and_controls(self):
        sensitive = (
            "token=sampleSecret password='two word secret' AKIA1234567890ABCDEF "
            "Bearer sampleBearer https://user:password@example.org/video?token=private "
            "'GOOGLE_OAUTH_CLIENT_SECRET': 'oauthSecret' Basic sampleBasic "
            "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.signature "
            r"C:\Users\kemal\private.mp4 /uploads/private/video.mp4 /usr/lib/libcudnn.so.9 "
            "\x1b[31mCUDA 12.6 cuDNN 9\x00\n" + "z" * 5000
        )
        error = GpuPreflightError("cuda_session_initialization_failed", stage="session_creation")
        error.__cause__ = RuntimeError(sensitive)
        record = self.failed_main_record(error)
        detail = record["causes"][0]["message"]
        self.assertLessEqual(len(detail), 1024)
        for removed in ("sampleSecret", "two word secret", "AKIA1234567890ABCDEF", "sampleBearer",
                        "example.org", "oauthSecret", "sampleBasic", "eyJhbGci", "kemal", "private.mp4", "video.mp4", "\x1b", "\x00", "\n"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, detail)
        self.assertIn("libcudnn.so.9", detail)
        self.assertIn("CUDA 12.6 cuDNN 9", detail)

    def test_diagnostic_chains_are_cycle_safe_and_unprintable_causes_do_not_mask_failure(self):
        class BadDetail(RuntimeError):
            def __str__(self):
                raise ValueError("broken exception formatter")

        error = GpuPreflightError("cuda_session_initialization_failed", stage="session_creation")
        first, second = BadDetail(), RuntimeError("CUDA error 35")
        first.__cause__ = second
        second.__cause__ = first
        error.__cause__ = first
        record = self.failed_main_record(error)
        self.assertEqual(len(record["causes"]), 2)
        self.assertEqual(record["causes"][0]["message"], "<exception detail unavailable>")
        self.assertIn("CUDA error 35", record["causes"][1]["message"])
        for _ in range(10):
            cause = RuntimeError("extra cause")
            cause.__cause__ = error.__cause__
            error.__cause__ = cause
        self.assertEqual(len(_failure_record(error, "gpu_runtime")["causes"]), 3)

    def test_unexpected_runtime_exception_is_reported_and_still_exits_two(self):
        record = self.failed_main_record(RuntimeError("unexpected runtime error token=privateValue"))
        self.assertEqual(record["error"], "preflight_unexpected_failure")
        self.assertEqual(record["stage"], "gpu_runtime")
        self.assertNotIn("privateValue", json.dumps(record))

    def test_closed_diagnostic_output_does_not_change_the_failure_result(self):
        failure = GpuPreflightError("cuda_session_initialization_failed", stage="session_creation")
        with patch("sys.argv", ["gpu_preflight", "--model", str(self.model)]), \
             patch("aws_app.gpu_model_integrity.verify_gpu_model"), \
             patch("aws_app.gpu_preflight.validate_gpu_runtime", side_effect=failure), \
             patch("builtins.print", side_effect=BrokenPipeError("closed log pipe")), \
             self.assertLogs("aws_app.gpu_preflight", level="ERROR"):
            self.assertEqual(main(), 2)


if __name__ == "__main__":
    unittest.main()
