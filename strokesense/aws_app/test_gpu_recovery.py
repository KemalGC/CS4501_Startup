"""Offline recovery tests for stale GSI, lost SQS acknowledgments and ECS STOPPED."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from aws_app.core import AwsBackend, Settings, _item, _user_hash
from aws_app.gpu_recovery import reconcile_due_gpu_jobs, lambda_handler


class RecoveryStore:
    def __init__(self, now):
        self.now = now
        self.job = "d" * 32
        owner_hash = _user_hash("owner")
        self.record = {
            "job_id": self.job,
            "user_id": "owner",
            "tier": "paid",
            "status": "gpu_queued",
            "expires_at": now - 2,
            "gpu_queued_at": now - 120,
            "s3_key": f"uploads/{owner_hash}/{self.job}/original.mp4",
            "report_key": f"reports/paid/{owner_hash}/{self.job}/report.json",
        }
        self.index_rows = {"gpu_queued": [dict(self.record)], "gpu_dispatching": [],
                           "gpu_submitted": []}
        self.updates = []

    def query(self, **kwargs):
        status = kwargs["ExpressionAttributeValues"][":state"]["S"]
        assert kwargs["IndexName"] == "status-expires_at-index"
        assert kwargs["KeyConditionExpression"].endswith("expires_at < :now")
        assert kwargs["Limit"] <= 25
        return {"Items": [_item(r) for r in self.index_rows[status]]}

    def get_item(self, **kwargs):
        assert kwargs.get("ConsistentRead") is True
        return {"Item": _item(self.record)} if self.record else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        assert kwargs["Key"]["job_id"]["S"] == self.job
        assert kwargs["ExpressionAttributeValues"][":uid"]["S"] == "owner"


class GpuRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.store = RecoveryStore(self.now)
        self.ddb = SimpleNamespace(
            query=self.store.query,
            get_item=self.store.get_item,
            update_item=self.store.update_item,
        )
        self.service = AwsBackend(
            Settings("bucket", "users", "jobs",
                     paid_billing_enabled=True, paid_gpu_enabled=True, gpu_dispatch_ready=True),
            self.ddb, MagicMock(), clock=lambda: self.now,
        )
        self.ecs, self.sqs = MagicMock(), MagicMock()
        self.config = SimpleNamespace(check=lambda: None)
        self.queue_url = "https://sqs.us-east-1.amazonaws.com/123456789012/strokesense-paid-gpu.fifo"

    def recover(self):
        return reconcile_due_gpu_jobs(
            self.service, sqs=self.sqs, ecs=self.ecs, config=self.config,
            queue_url=self.queue_url,
        )

    def test_lost_sqs_ack_retries_only_opaque_job_id_and_postpones_outbox(self):
        outcome = self.recover()
        self.assertEqual(outcome["outbox_retried"], 1)
        self.assertEqual(outcome["errors"], 0)
        message = self.sqs.send_message.call_args.kwargs
        self.assertEqual(message["MessageGroupId"], "single-paid-gpu")
        self.assertEqual(json.loads(message["MessageBody"]), {"v": 1, "job_id": self.store.job})
        self.assertTrue(message["MessageDeduplicationId"].startswith(self.store.job + "-outbox-"))
        self.assertNotIn("user_id", message["MessageBody"])
        self.assertNotIn("s3_key", message["MessageBody"])
        self.assertEqual(len(self.store.updates), 1)
        update = self.store.updates[0]
        self.assertIn("expires_at < :now", update["ConditionExpression"])
        self.assertEqual(int(update["ExpressionAttributeValues"][":next_due"]["N"]),
                         self.now + 900)

    def test_stale_gsi_cannot_resurrect_a_settled_or_deleted_job(self):
        for status in ("failed", "deleting"):
            with self.subTest(status=status):
                self.store.record["status"] = status
                self.assertEqual(self.recover()["examined"], 1)
                self.sqs.send_message.assert_not_called()
        self.store.record = None
        self.recover()
        self.sqs.send_message.assert_not_called()

    def test_old_unconfirmed_outbox_is_left_for_manual_review(self):
        self.store.record["gpu_queued_at"] = self.now - 90000
        outcome = self.recover()
        self.assertEqual(outcome["manual_review"], 1)
        self.assertEqual(outcome["errors"], 0)
        self.sqs.send_message.assert_not_called()

    def test_ambiguous_gpu_dispatch_is_never_automatically_relaunched(self):
        self.store.record["status"] = "gpu_dispatching"
        self.store.index_rows = {"gpu_queued": [], "gpu_dispatching": [dict(self.store.record)],
                                 "gpu_submitted": []}
        result = self.recover()
        self.assertEqual(result["manual_review"], 1)
        self.ecs.run_task.assert_not_called()
        self.sqs.send_message.assert_not_called()

    def test_running_ecs_task_reschedules_poll_without_spending_credits(self):
        self.store.record.update(
            status="gpu_submitted", gpu_task_deadline_epoch=self.now + 1500,
            ecs_task_arn="arn:aws:ecs:us-east-1:123:task/gpu/job",
        )
        self.store.index_rows = {"gpu_queued": [], "gpu_dispatching": [],
                                 "gpu_submitted": [dict(self.store.record)]}
        with patch("aws_app.gpu_recovery.reconcile_gpu_job", return_value={
            "job_id": self.store.job, "status": "gpu_submitted",
        }) as settle:
            result = self.recover()
        self.assertEqual(result["poll_rescheduled"], 1)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(int(self.store.updates[0]["ExpressionAttributeValues"][":next_due"]["N"]),
                         self.now + 900)
        settle.assert_called_once()
        self.sqs.send_message.assert_not_called()

    def test_ecs_stopped_is_settled_without_replaying_queue(self):
        self.store.record.update(status="gpu_submitted",
                                 gpu_task_deadline_epoch=self.now + 1000)
        self.store.index_rows = {"gpu_queued": [], "gpu_dispatching": [],
                                 "gpu_submitted": [dict(self.store.record)]}
        with patch("aws_app.gpu_recovery.reconcile_gpu_job", return_value={
            "job_id": self.store.job, "status": "succeeded",
        }):
            result = self.recover()
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["poll_rescheduled"], 0)
        self.sqs.send_message.assert_not_called()
        self.assertEqual(self.store.updates, [])

    def test_overdue_gpu_task_stays_reserved_for_review(self):
        self.store.record.update(status="gpu_submitted",
                                 ecs_task_arn="arn:aws:ecs:us-east-1:123:task/gpu/job",
                                 gpu_task_deadline_epoch=self.now - 10)
        self.store.index_rows = {"gpu_queued": [], "gpu_dispatching": [],
                                 "gpu_submitted": [dict(self.store.record)]}
        with patch("aws_app.gpu_recovery.reconcile_gpu_job", return_value={
            "job_id": self.store.job, "status": "gpu_submitted",
        }):
            result = self.recover()
        self.assertEqual(result["manual_review"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(self.store.updates, [])

    def test_lambda_stays_off_before_importing_cloud_apis(self):
        with patch.dict(os.environ, {"GPU_RECONCILE_ENABLED": "false"}):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                lambda_handler({"source": "aws.events"}, None)


if __name__ == "__main__":
    unittest.main()
