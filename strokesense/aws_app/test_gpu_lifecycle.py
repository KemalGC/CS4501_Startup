"""Offline ECS STOPPED credit settlement; no paid AWS resources are used."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import unittest

from aws_app.core import ApiError, AwsBackend, Settings
from aws_app.gpu_dispatcher import GpuDispatcherConfig
from aws_app.gpu_lifecycle import reconcile_gpu_job
from aws_app.test_backend import FakeS3, MemoryDynamo


class GpuLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.ddb = MemoryDynamo()
        self.s3 = FakeS3()
        self.service = AwsBackend(
            Settings("private", "users", "jobs",
                     paid_billing_enabled=True, paid_gpu_enabled=True, gpu_dispatch_ready=True),
            self.ddb, self.s3, clock=lambda: self.now,
        )
        self.service._account("owner")
        self.ddb.accounts["owner"].update({
            "paid_membership_status": "active",
            "paid_membership_expires_at": self.now + 10000,
            "paid_credits_available": 2,
        })
        self.job = self.service.start_upload("owner", {
            "tier": "paid", "content_type": "video/mp4", "size_bytes": 1_000_000
        })["video_id"]
        self.arn = "arn:aws:ecs:us-east-1:123456789012:task/gpu/taskABC"
        self.ddb.jobs[self.job]["status"] = "gpu_submitted"
        self.ddb.jobs[self.job]["ecs_task_arn"] = self.arn
        self.config = GpuDispatcherConfig(
            cluster="arn:aws:ecs:us-east-1:123456789012:cluster/gpu",
            task_definition="arn:aws:ecs:us-east-1:123456789012:task-definition/gpu:1",
            capacity_provider="gpu-reviewed", subnets=("subnet-12345678",),
            security_groups=("sg-12345678",), bucket="private", enabled=True,
        )
        self.ecs = MagicMock()
        self.ecs.describe_tasks.return_value = {
            "tasks": [{"taskArn": self.arn, "lastStatus": "STOPPED",
                       "containers": [{"name": "paid-gpu-worker", "exitCode": 0}]}],
        }

    def settle(self):
        # MemoryDynamo supports paid credit DynamoDB transactions but not
        # the unrelated global slot release update.
        with patch.object(self.ddb, "update_item", return_value={}):
            return reconcile_gpu_job(self.service, self.ecs, self.config, self.job)

    def test_success_consumes_exactly_one_reserved_paid_credit(self):
        self.s3.objects[self.ddb.jobs[self.job]["report_key"]] = 1000
        self.assertEqual(self.settle()["status"], "succeeded")
        owner = self.ddb.accounts["owner"]
        self.assertEqual(owner["paid_credits_available"], 1)
        self.assertEqual(owner["paid_credits_reserved"], 0)
        self.assertEqual(owner["paid_credits_used"], 1)
        self.assertEqual(self.settle()["status"], "succeeded")
        self.assertEqual(owner["paid_credits_used"], 1)
        self.assertGreater(self.ddb.jobs[self.job]["report_expires_at"], self.now)

    def test_gpu_failure_refunds_reserved_credit_exactly_once(self):
        self.ecs.describe_tasks.return_value["tasks"][0]["containers"][0]["exitCode"] = 2
        self.assertEqual(self.settle()["status"], "failed")
        owner = self.ddb.accounts["owner"]
        self.assertEqual(owner["paid_credits_available"], 2)
        self.assertEqual(owner["paid_credits_reserved"], 0)
        self.assertEqual(owner["paid_credits_used"], 0)
        self.assertEqual(self.settle()["status"], "failed")
        self.assertEqual(owner["paid_credits_available"], 2)

    def test_missing_report_cannot_be_charged_as_success(self):
        self.assertEqual(self.settle()["status"], "failed")
        self.assertEqual(self.ddb.accounts["owner"]["paid_credits_reserved"], 0)
        self.assertEqual(self.ddb.accounts["owner"]["paid_credits_available"], 2)

    def test_ambiguous_ecs_state_does_not_refund_or_consume(self):
        for response in [
            {"tasks": [{"taskArn": self.arn, "lastStatus": "RUNNING"}]},
            {"tasks": []}, {"failures": [{"reason": "UNKNOWN"}]},
            {"tasks": [{"taskArn": self.arn, "lastStatus": "STOPPED", "containers": []}]},
        ]:
            self.ecs.describe_tasks.return_value = response
            try:
                outcome = self.settle()
            except ApiError:
                pass
            else:
                self.assertEqual(outcome["status"], "gpu_submitted")
            self.assertEqual(self.ddb.accounts["owner"]["paid_credits_reserved"], 1)
            self.assertEqual(self.ddb.accounts["owner"]["paid_credits_used"], 0)
            self.assertEqual(self.ddb.accounts["owner"]["paid_credits_available"], 1)


if __name__ == "__main__":
    unittest.main()
