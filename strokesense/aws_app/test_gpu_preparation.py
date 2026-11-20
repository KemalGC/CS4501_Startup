"""Paid membership and GPU preflight preparation, no hardware or AWS calls."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from aws_app.core import ApiError, AwsBackend, Settings, _item
from aws_app.gpu_preflight import GpuPreflightError, validate_gpu_runtime
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
    def ort(available, active):
        return SimpleNamespace(
            get_available_providers=lambda: available,
            SessionOptions=lambda: SimpleNamespace(add_session_config_entry=lambda *_args: None),
            InferenceSession=lambda *args, **kwargs: SimpleNamespace(
                get_providers=lambda: active,
                disable_fallback=lambda: None,
            ),
        )

    def test_cuda_model_session_and_vram_must_be_real(self):
        ort = self.ort(["CUDAExecutionProvider", "CPUExecutionProvider"],
                       ["CUDAExecutionProvider", "CPUExecutionProvider"])
        result = validate_gpu_runtime(
            self.model, run=self.nvidia_memory(),
            import_module=lambda _name: ort,
        )
        self.assertEqual(result["provider"], "CUDAExecutionProvider")
        self.assertEqual(result["gpu_memory_total_mib"], 3072)

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


if __name__ == "__main__":
    unittest.main()
