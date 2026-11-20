"""No-network paid GPU queue, ECS and lock contract tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
import unittest

from aws_app.core import ApiError, AwsBackend, Settings, _item, _user_hash
from aws_app.gpu_dispatcher import (
    GpuDispatcherConfig, dispatch_gpu_task, enqueue_paid_analysis, GPU_LOCK_ID,
)


class FakeState:
    def __init__(self, now):
        self.now = now
        self.accounts = {"owner": {
            "user_id": "owner", "paid_membership_status": "active",
            "paid_membership_expires_at": now + 4000,
            "paid_credits_available": 1, "paid_credits_reserved": 1,
        }}
        job = "a" * 32
        digest = _user_hash("owner")
        self.jobs = {job: {
            "job_id": job, "user_id": "owner", "tier": "paid",
            "status": "uploaded", "size_bytes": 50000000,
            "s3_key": f"uploads/{digest}/{job}/original.mp4",
            "report_key": f"reports/paid/{digest}/{job}/report.json",
        }}
        self.calls = []

    def get_item(self, **kwargs):
        table = kwargs["TableName"]
        key = kwargs["Key"]
        record = self.accounts.get(key["user_id"]["S"]) if table == "users" else self.jobs.get(key["job_id"]["S"])
        return {"Item": _item(record)} if record else {}

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        values = kwargs["ExpressionAttributeValues"]
        if kwargs["TableName"] == "users":
            lock = self.accounts.setdefault(GPU_LOCK_ID, {})
            current = lock.get("active_job")
            if current and current != values[":job"]["S"] and lock["active_job_expires_at"] > self.now:
                err = Exception("ConditionalCheckFailedException")
                err.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
                raise err
            lock.update(active_job=values[":job"]["S"],
                        active_job_expires_at=int(values[":expiry"]["N"]))
            return {}
        job_id = kwargs["Key"]["job_id"]["S"]
        current = self.jobs[job_id]
        if values.get(":paid", {}).get("S") != "paid":
            raise AssertionError("paid condition missing")
        if ":pending" in values:
            assert current["status"] == "uploaded"
            current["status"] = "gpu_queued"
        elif ":dispatching" in values and ":queued" in values:
            assert current["status"] == "gpu_queued"
            current["status"] = "gpu_dispatching"
        elif ":running" in values:
            assert current["status"] == "gpu_dispatching"
            current["status"] = "gpu_submitted"
            current["ecs_task_arn"] = values[":arn"]["S"]
        return {}


class GpuDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.store = FakeState(self.now)
        self.ddb = SimpleNamespace(get_item=self.store.get_item, update_item=self.store.update_item)
        self.service = AwsBackend(Settings(
            "private-media", "users", "jobs",
            paid_billing_enabled=True, paid_gpu_enabled=True, gpu_dispatch_ready=True,
        ), self.ddb, MagicMock(), clock=lambda: self.now)
        self.id = "a" * 32
        self.queue = MagicMock()
        self.ecs = MagicMock()
        self.task_def = {
            "requiresCompatibilities": ["MANAGED_INSTANCES"],
            "networkMode": "awsvpc",
            "containerDefinitions": [{
                "name": "paid-gpu-worker",
                "image": "ecr.aws/my-private-gpu@sha256:" + "b" * 64,
                "resourceRequirements": [{"type": "GPU", "value": "0.125"}],
            }],
        }
        self.ecs.describe_task_definition.return_value = {"taskDefinition": self.task_def}
        self.ecs.run_task.return_value = {
            "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task123"}],
            "failures": [],
        }
        self.config = GpuDispatcherConfig(
            cluster="arn:aws:ecs:us-east-1:123456789012:cluster/gpu",
            task_definition="arn:aws:ecs:us-east-1:123456789012:task-definition/gpu:1",
            capacity_provider="gpu-reviewed",
            subnets=("subnet-12345678",),
            security_groups=("sg-12345678",),
            bucket="private-media",
            enabled=True,
        )

    def test_paid_message_only_after_strong_owner_and_membership_checks(self):
        with self.assertRaises(ApiError):
            enqueue_paid_analysis(self.service, "stranger", self.id, sqs=self.queue,
                                  queue_url="https://sqs.us-east-1.amazonaws.com/12345/gpu.fifo", enabled=True)
        self.queue.send_message.assert_not_called()
        response = enqueue_paid_analysis(self.service, "owner", self.id, sqs=self.queue,
                                         queue_url="https://sqs.us-east-1.amazonaws.com/12345/gpu.fifo",
                                         enabled=True)
        self.assertTrue(response["dispatch_confirmed"])
        self.assertEqual(self.store.jobs[self.id]["status"], "gpu_queued")
        sent = self.queue.send_message.call_args.kwargs
        self.assertEqual(sent["MessageGroupId"], "single-paid-gpu")
        self.assertEqual(sent["MessageDeduplicationId"], self.id)
        self.assertNotIn("user_id", sent["MessageBody"])
        self.assertNotIn("s3_key", sent["MessageBody"])

    def test_gpu_launch_is_idempotent_and_never_fargate(self):
        self.store.jobs[self.id]["status"] = "gpu_queued"
        outcome = dispatch_gpu_task(self.service, self.ecs, self.config, self.id)
        self.assertIn("ecs_task_arn", outcome)
        call = self.ecs.run_task.call_args.kwargs
        self.assertNotIn("launchType", call)
        self.assertEqual(call["count"], 1)
        self.assertEqual(call["capacityProviderStrategy"][0]["capacityProvider"], "gpu-reviewed")
        self.assertEqual(call["clientToken"], "strokesense-paid-gpu-" + self.id)
        fields = {v["name"]: v["value"] for v in call["overrides"]["containerOverrides"][0]["environment"]}
        self.assertEqual(fields["STROKESENSE_PAID_GPU_WORKER_ENABLED"], "true")
        self.assertEqual(fields["STROKESENSE_REPORT_KEY"], self.store.jobs[self.id]["report_key"])
        self.assertEqual(self.store.accounts[GPU_LOCK_ID]["active_job"], self.id)
        # Duplicate FIFO delivery after persisted task must not start a second task.
        again = dispatch_gpu_task(self.service, self.ecs, self.config, self.id)
        self.assertEqual(again, outcome)
        self.assertEqual(self.ecs.run_task.call_count, 1)

    def test_wrong_gpu_resource_and_mutable_image_are_rejected(self):
        self.store.jobs[self.id]["status"] = "gpu_queued"
        for image, resource in [
            ("image:latest", "0.125"), ("image@sha256:" + "a" * 64, "1"),
        ]:
            with self.subTest(image=image, resource=resource):
                self.task_def["containerDefinitions"][0]["image"] = image
                self.task_def["containerDefinitions"][0]["resourceRequirements"][0]["value"] = resource
                with self.assertRaises(ApiError) as err:
                    dispatch_gpu_task(self.service, self.ecs, self.config, self.id)
                self.assertEqual(err.exception.code, "gpu_task_unapproved")
        self.ecs.run_task.assert_not_called()

    def test_worker_and_ecs_are_not_invoked_without_gate(self):
        disabled = GpuDispatcherConfig(**{**self.config.__dict__, "enabled": False})
        self.store.jobs[self.id]["status"] = "gpu_queued"
        with self.assertRaises(ApiError):
            dispatch_gpu_task(self.service, self.ecs, disabled, self.id)
        self.ecs.run_task.assert_not_called()

    def test_global_single_gpu_slot_blocks_another_paid_job(self):
        self.store.jobs[self.id]["status"] = "gpu_queued"
        self.store.accounts[GPU_LOCK_ID] = {
            "active_job": "b" * 32,
            "active_job_expires_at": self.now + 100,
        }
        with self.assertRaises(ApiError) as err:
            dispatch_gpu_task(self.service, self.ecs, self.config, self.id)
        self.assertEqual(err.exception.code, "gpu_capacity_busy")
        self.ecs.run_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
