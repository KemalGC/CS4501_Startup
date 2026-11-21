"""SQS FIFO entry point for a future GPU ECS dispatcher.

This Lambda's Terraform mapping and internal enable flag are both disabled.
It never trusts a claimed user ID, S3 path, subscription or price in the
message. One message references only a job ID, which is strongly re-read
from DynamoDB and validated by the paid GPU dispatcher.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable

from .core import AwsBackend, Settings
from .gpu_dispatcher import GpuDispatcherConfig, dispatch_gpu_task

LOGGER = logging.getLogger(__name__)
JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
MAX_MESSAGE_BYTES = 512
GROUP_ID = "single-paid-gpu"


def parse_paid_job_message(record: dict[str, Any], *, expected_source_arn: str) -> tuple[str, str]:
    """Reject anything but one trusted FIFO message with an opaque job ID."""
    if not isinstance(record, dict) or record.get("eventSource") != "aws:sqs":
        raise ValueError("unexpected_event_source")
    if not expected_source_arn or record.get("eventSourceARN") != expected_source_arn:
        raise ValueError("wrong_paid_queue")
    attributes = record.get("attributes")
    if not isinstance(attributes, dict) or attributes.get("MessageGroupId") != GROUP_ID:
        raise ValueError("wrong_message_group")
    message_id = record.get("messageId")
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 128:
        raise ValueError("invalid_message_id")
    body = record.get("body")
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("invalid_gpu_message")
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_gpu_message") from exc
    if (not isinstance(payload, dict) or set(payload) != {"v", "job_id"}
            or type(payload["v"]) is not int or payload["v"] != 1
            or not isinstance(payload["job_id"], str)
            or not JOB_ID.fullmatch(payload["job_id"])):
        raise ValueError("invalid_gpu_message")
    return message_id, payload["job_id"]


def process_gpu_batch(
    event: dict[str, Any], *,
    service: AwsBackend,
    ecs: Any,
    config: GpuDispatcherConfig,
    expected_source_arn: str,
    dispatcher: Callable[..., dict[str, str]] = dispatch_gpu_task,
) -> dict[str, list[dict[str, str]]]:
    """One-message batches, partial failure so SQS retries rather than dropping."""
    records = event.get("Records")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("gpu_dispatcher_requires_batch_size_one")
    record = records[0]
    message_id = record.get("messageId") if isinstance(record, dict) else None
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 128:
        raise ValueError("invalid_message_id")
    try:
        _, job_id = parse_paid_job_message(record, expected_source_arn=expected_source_arn)
        config.check()
        dispatcher(service, ecs, config, job_id)
    except Exception:
        # No raw exception to logs: client-supplied SQS messages can contain
        # sensitive data. With ReportBatchItemFailures AWS will retry then DLQ.
        LOGGER.warning("Paid GPU queue dispatch failed; message will be retried")
        return {"batchItemFailures": [{"itemIdentifier": message_id}]}
    return {"batchItemFailures": []}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    # Dual safety gate: the Terraform mapping is also created disabled.
    if os.getenv("GPU_DISPATCH_ENABLED") != "true":
        raise RuntimeError("Paid GPU dispatch is disabled")
    expected = os.getenv("GPU_SQS_SOURCE_ARN", "")
    if not expected:
        raise RuntimeError("Paid GPU FIFO queue is not configured")
    import boto3

    cfg = Settings.from_env()
    config = GpuDispatcherConfig(
        cluster=os.getenv("GPU_ECS_CLUSTER", ""),
        task_definition=os.getenv("GPU_ECS_TASK_DEFINITION", ""),
        capacity_provider=os.getenv("GPU_ECS_CAPACITY_PROVIDER", ""),
        subnets=tuple(x for x in os.getenv("GPU_SUBNET_IDS", "").split(",") if x),
        security_groups=tuple(x for x in os.getenv("GPU_SECURITY_GROUP_IDS", "").split(",") if x),
        bucket=cfg.bucket,
        enabled=cfg.paid_gpu_enabled and cfg.gpu_dispatch_ready,
    )
    config.check()
    service = AwsBackend(
        cfg, dynamodb=boto3.client("dynamodb"), s3=boto3.client("s3"),
        batch=None,
    )
    return process_gpu_batch(
        event, service=service, ecs=boto3.client("ecs"),
        config=config, expected_source_arn=expected,
    )
