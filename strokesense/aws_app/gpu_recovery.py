"""Operator-gated recovery for paid GPU queue and ECS task results.

NOT wired to production. The scheduled Lambda is disabled in Terraform, has
a second runtime flag, and cannot create GPU capacity or collect payments.

Only jobs *due* on the status/expiry GSI are examined. The index is eventually
consistent: every candidate is checked again through the base DynamoDB table
with ConsistentRead before any state change or queue send.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any

from .core import ApiError, AwsBackend, Settings, _decode, _is_conditional, _n, _s
from .gpu_dispatcher import GpuDispatcherConfig, _keys
from .gpu_lifecycle import reconcile_gpu_job

LOGGER = logging.getLogger(__name__)
DUE_STATES = ("gpu_queued", "gpu_dispatching", "gpu_submitted")
JOB_RE = re.compile(r"[a-f0-9]{32}\Z")
ONE_ATTEMPT_SECONDS = 15 * 60
MAX_OUTBOX_AGE_SECONDS = 24 * 3600
MAX_QUERY_LIMIT = 25


def _queue_retry(service: AwsBackend, sqs: Any, queue_url: str, record: dict[str, Any], now: int) -> None:
    job = record["job_id"]
    if not (queue_url.startswith("https://sqs.") and queue_url.endswith(".fifo")):
        raise ApiError(503, "gpu_queue_not_configured", "GPU FIFO queue is not configured")
    timestamp = record.get("gpu_queued_at")
    if type(timestamp) is not int or timestamp > now or now - timestamp > MAX_OUTBOX_AGE_SECONDS:
        # Old outbox entries must be reconciled by an operator. In particular
        # do not retry ECS task creation outside the idempotency window.
        raise ApiError(409, "gpu_outbox_manual_review", "GPU queue delivery needs manual review")
    # The original SendMessage may have succeeded right before a timeout.
    # SQS 5-minute deduplication and ECS RunTask's stable clientToken provide
    # separate protections. A unique 15-minute replay window lets a retry
    # actually arrive if the initial send was never accepted.
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"v": 1, "job_id": job}, separators=(",", ":")),
        MessageGroupId="single-paid-gpu",
        MessageDeduplicationId=f"{job}-outbox-{now // ONE_ATTEMPT_SECONDS}",
    )
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job)},
            UpdateExpression="SET expires_at = :next_due",
            ConditionExpression="user_id = :uid AND #state = :queued AND expires_at < :now",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={
                ":uid": _s(record["user_id"]), ":queued": _s("gpu_queued"),
                ":now": _n(now), ":next_due": _n(now + ONE_ATTEMPT_SECONDS),
            },
        )
    except Exception as exc:
        if not _is_conditional(exc):
            raise
        # SQS may have accepted the message but the job advanced concurrently.
        # Rechecking the owner/state is handled by the queue consumer.


def _reschedule_gpu_poll(service: AwsBackend, record: dict[str, Any], now: int) -> None:
    deadline = record.get("gpu_task_deadline_epoch")
    if type(deadline) is not int or now >= deadline:
        raise ApiError(409, "gpu_task_manual_review",
                       "GPU task deadline reached without confirmed STOPPED status")
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(record["job_id"])},
            UpdateExpression="SET expires_at = :next_due",
            ConditionExpression=(
                "user_id = :uid AND #state = :running AND ecs_task_arn = :task "
                "AND expires_at < :now"
            ),
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={
                ":uid": _s(record["user_id"]), ":running": _s("gpu_submitted"),
                ":task": _s(record["ecs_task_arn"]), ":now": _n(now),
                ":next_due": _n(now + ONE_ATTEMPT_SECONDS),
            },
        )
    except Exception as exc:
        if not _is_conditional(exc):
            raise


def reconcile_due_gpu_jobs(
    service: AwsBackend, *, sqs: Any, ecs: Any, config: GpuDispatcherConfig,
    queue_url: str, per_state_limit: int = MAX_QUERY_LIMIT,
) -> dict[str, int]:
    """Recover lost FIFO send acknowledgments and settle authoritative ECS exits.

    Indeterminate dispatches remain in gpu_dispatching and are NEVER refunded,
    released, or blindly relaunched by this scheduled reconciler.
    """
    config.check()
    if not 1 <= per_state_limit <= MAX_QUERY_LIMIT:
        raise ValueError("gpu_per_state_limit must be in 1..25")
    now = service._now()
    counts = {
        "examined": 0, "outbox_retried": 0, "poll_rescheduled": 0,
        "succeeded": 0, "failed": 0, "pending": 0,
        "manual_review": 0, "errors": 0, "truncated_states": 0,
    }
    for state in DUE_STATES:
        page = service.ddb.query(
            TableName=service.cfg.jobs_table,
            IndexName="status-expires_at-index",
            KeyConditionExpression="#state = :state AND expires_at < :now",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":state": _s(state), ":now": _n(now)},
            Limit=per_state_limit,
        )
        if page.get("LastEvaluatedKey"):
            counts["truncated_states"] += 1
        for raw in page.get("Items", []):
            counts["examined"] += 1
            indexed = _decode(raw)
            job_id = indexed.get("job_id")
            owner = indexed.get("user_id")
            if (not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id)
                    or not isinstance(owner, str) or not owner):
                counts["errors"] += 1
                continue
            try:
                # The GSI may show an already-settled/deleted item.
                item = service.ddb.get_item(
                    TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)},
                    ConsistentRead=True,
                )
                current = _decode(item["Item"]) if item.get("Item") else {}
                if (current.get("user_id") != owner or current.get("status") != state
                        or type(current.get("expires_at")) is not int
                        or current["expires_at"] >= now):
                    continue
                _keys(current)  # Verify paid tier and owner-derived private keys.
                if state == "gpu_queued":
                    _queue_retry(service, sqs, queue_url, current, now)
                    counts["outbox_retried"] += 1
                elif state == "gpu_dispatching":
                    # RunTask might have succeeded before its ARN was saved.
                    # Only an operator can resolve an old ambiguous launch.
                    counts["manual_review"] += 1
                else:
                    outcome = reconcile_gpu_job(service, ecs, config, job_id)
                    terminal = outcome["status"]
                    if terminal in ("succeeded", "failed"):
                        counts[terminal] += 1
                    else:
                        _reschedule_gpu_poll(service, current, now)
                        counts["pending"] += 1
                        counts["poll_rescheduled"] += 1
            except ApiError as exc:
                if exc.code in ("gpu_outbox_manual_review", "gpu_task_manual_review"):
                    counts["manual_review"] += 1
                else:
                    counts["errors"] += 1
                LOGGER.warning("GPU job recovery encountered a guarded condition")
            except Exception:
                counts["errors"] += 1
                LOGGER.exception("GPU job recovery failed; credits and task state unchanged")
    return counts


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    """Scheduled only, with an explicit off switch and rule identity check."""
    if os.getenv("GPU_RECONCILE_ENABLED") != "true":
        raise RuntimeError("GPU reconciliation is disabled")
    rule = os.getenv("GPU_RECONCILE_RULE_ARN")
    if (not rule or event.get("source") != "aws.events"
            or rule not in (event.get("resources") or [])):
        raise ValueError("Unexpected GPU reconciliation trigger")
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
    service = AwsBackend(
        cfg, dynamodb=boto3.client("dynamodb"), s3=boto3.client("s3"), batch=None,
    )
    result = reconcile_due_gpu_jobs(
        service, sqs=boto3.client("sqs"), ecs=boto3.client("ecs"),
        config=config, queue_url=os.getenv("GPU_SQS_QUEUE_URL", ""),
    )
    LOGGER.info("GPU reconciliation counters: %s", result)
    if result["errors"] or result["manual_review"]:
        raise RuntimeError("GPU reconciliation requires operator attention")
    return result
