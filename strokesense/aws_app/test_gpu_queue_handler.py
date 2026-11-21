"""SQS FIFO boundary validation and disabled-by-default paid GPU dispatcher.

All tests are offline: no AWS clients, credentials, GPUs or payment records.
"""
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aws_app.gpu_queue_handler import (
    GROUP_ID, parse_paid_job_message, process_gpu_batch, lambda_handler,
)

SOURCE = "arn:aws:sqs:us-east-1:123456789012:strokesense-dev-paid-gpu-jobs.fifo"
JOB = "a" * 32


def message(body=None, **changes):
    record = {
        "eventSource": "aws:sqs",
        "eventSourceARN": SOURCE,
        "messageId": "1234-test-message",
        "attributes": {"MessageGroupId": GROUP_ID},
        "body": json.dumps({"v": 1, "job_id": JOB}) if body is None else body,
    }
    record.update(changes)
    return record


class GpuQueueHandlerTests(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.ecs = MagicMock()
        self.config = SimpleNamespace(check=MagicMock())

    def test_requires_exact_opaque_job_id_and_dedicated_queue(self):
        record = message()
        self.assertEqual(parse_paid_job_message(record, expected_source_arn=SOURCE),
                         ("1234-test-message", JOB))
        bad = [
            message(eventSourceARN="arn:aws:sqs:wrong"),
            message(attributes={"MessageGroupId": "wrong"}),
            message(body='{"v":1,"job_id":"not-an-id"}'),
            message(body='{"v":1,"job_id":"' + JOB + '","s3_key":"steal-me"}'),
            message(body='{"v":1,"job_id":"' + JOB + '","user_id":"other"}'),
            message(body='{"v":true,"job_id":"' + JOB + '"}'),
            message(body="x" * 513),
        ]
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                parse_paid_job_message(entry, expected_source_arn=SOURCE)

    def test_valid_fifo_event_invokes_isolated_dispatcher_once(self):
        caller = MagicMock(return_value={"job_id": JOB, "ecs_task_arn": "task"})
        result = process_gpu_batch(
            {"Records": [message()]}, service=self.service, ecs=self.ecs,
            config=self.config, expected_source_arn=SOURCE, dispatcher=caller,
        )
        self.assertEqual(result, {"batchItemFailures": []})
        caller.assert_called_once_with(self.service, self.ecs, self.config, JOB)

    def test_bad_event_reports_retry_instead_of_acknowledging(self):
        caller = MagicMock()
        result = process_gpu_batch(
            {"Records": [message(body="not json")]}, service=self.service,
            ecs=self.ecs, config=self.config, expected_source_arn=SOURCE,
            dispatcher=caller,
        )
        self.assertEqual(result["batchItemFailures"],
                         [{"itemIdentifier": "1234-test-message"}])
        caller.assert_not_called()

    def test_gpu_run_task_failure_reports_retry_and_keeps_fifo_order(self):
        caller = MagicMock(side_effect=RuntimeError("scheduler disabled"))
        result = process_gpu_batch(
            {"Records": [message()]}, service=self.service, ecs=self.ecs,
            config=self.config, expected_source_arn=SOURCE, dispatcher=caller,
        )
        self.assertEqual(result["batchItemFailures"],
                         [{"itemIdentifier": "1234-test-message"}])
        caller.assert_called_once()
        with self.assertRaises(ValueError):
            process_gpu_batch(
                {"Records": [message(), message()]}, service=self.service,
                ecs=self.ecs, config=self.config, expected_source_arn=SOURCE,
                dispatcher=caller,
            )

    def test_real_lambda_handler_rejects_off_setting_before_importing_boto3(self):
        with patch.dict(os.environ, {"GPU_DISPATCH_ENABLED": "false"}):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                lambda_handler({"Records": [message()]}, None)


if __name__ == "__main__":
    unittest.main()
