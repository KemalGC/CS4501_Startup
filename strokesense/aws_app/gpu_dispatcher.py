"""Disabled-by-default ECS-on-EC2 paid GPU dispatcher for a future isolated FIFO queue.

This module is deliberately NOT wired into the production API or Lambda event
sources. It provides a real, testable RunTask implementation and one-task
DynamoDB admission lock; deployment still requires billing, completion/refund
reconciliation, reviewed GPU capacity, and explicit approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re
from datetime import datetime, timezone

from .core import ApiError, AwsBackend, _decode, _n, _s, _user_hash, _is_conditional
from .paid_access import require_paid_membership

_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_RESOURCE = re.compile(r"[A-Za-z0-9_:/.+=@-]{1,512}\Z")
_SUBNET = re.compile(r"subnet-[0-9a-f]{8,17}\Z")
_SG = re.compile(r"sg-[0-9a-f]{8,17}\Z")
GPU_LOCK_ID = "__strokesense_paid_gpu_single_slot__"
MAX_GPU_RUNTIME_SECONDS = 3300


@dataclass(frozen=True)
class GpuDispatcherConfig:
    cluster: str
    task_definition: str
    capacity_provider: str
    subnets: tuple[str, ...]
    security_groups: tuple[str, ...]
    bucket: str
    worker_container: str = "paid-gpu-worker"
    enabled: bool = False

    def check(self) -> None:
        if not self.enabled:
            raise ApiError(503, "gpu_dispatch_disabled", "Paid GPU dispatch is not enabled")
        if not all(_RESOURCE.fullmatch(x) for x in (self.cluster, self.task_definition, self.capacity_provider)):
            raise ApiError(503, "gpu_dispatch_not_configured", "GPU service configuration is invalid")
        if (not self.subnets or not self.security_groups or
                len(self.subnets) > 5 or len(self.security_groups) > 5 or
                not all(_SUBNET.fullmatch(x) for x in self.subnets) or
                not all(_SG.fullmatch(x) for x in self.security_groups)):
            raise ApiError(503, "gpu_dispatch_not_configured", "GPU networking is not configured")
        if not self.bucket or not _RESOURCE.fullmatch(self.bucket):
            raise ApiError(503, "gpu_dispatch_not_configured", "GPU media bucket is not configured")


def _keys(record: dict[str, Any]) -> tuple[str, str, str]:
    job = record.get("job_id")
    user = record.get("user_id")
    if (not isinstance(job, str) or not _JOB_ID.fullmatch(job)
            or not isinstance(user, str) or not user
            or record.get("tier") != "paid"):
        raise ApiError(409, "invalid_paid_job", "GPU job record is invalid")
    digest = _user_hash(user)
    original = record.get("s3_key")
    suffix = next((s for s in (".mp4", ".mov", ".webm")
                   if original == f"uploads/{digest}/{job}/original{s}"), None)
    report = f"reports/paid/{digest}/{job}/report.json"
    if suffix is None or record.get("report_key") != report:
        raise ApiError(409, "invalid_paid_job", "GPU job media identity is invalid")
    return digest, original, report


def _gpu_task_is_approved(ecs: Any, config: GpuDispatcherConfig) -> None:
    task = ecs.describe_task_definition(taskDefinition=config.task_definition)["taskDefinition"]
    containers = task.get("containerDefinitions") or []
    matching = [c for c in containers if c.get("name") == config.worker_container]
    if (len(matching) != 1 or "EC2" not in task.get("requiresCompatibilities", [])
            or task.get("networkMode") != "awsvpc"):
        raise ApiError(503, "gpu_task_unapproved", "GPU task definition has not been approved")
    image = matching[0].get("image")
    if (not isinstance(image, str) or not re.search(r"@sha256:[a-f0-9]{64}\Z", image)
            or {tuple(sorted(r.items())) for r in matching[0].get("resourceRequirements", [])}
            != {(("type", "GPU"), ("value", "0.125"))}):
        raise ApiError(503, "gpu_task_unapproved", "GPU image or resource requirements are unsafe")


def _run_request(config: GpuDispatcherConfig, record: dict[str, Any]) -> dict[str, Any]:
    owner_hash, original, report = _keys(record)
    job_id = record["job_id"]
    return {
        "cluster": config.cluster,
        "taskDefinition": config.task_definition,
        "capacityProviderStrategy": [{"capacityProvider": config.capacity_provider, "weight": 1}],
        "count": 1,
        "clientToken": "strokesense-paid-gpu-" + job_id,
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": list(config.subnets),
                "securityGroups": list(config.security_groups),
                "assignPublicIp": "DISABLED",
            }
        },
        "overrides": {"containerOverrides": [{
            "name": config.worker_container,
            "environment": [
                {"name": "STROKESENSE_PAID_GPU_WORKER_ENABLED", "value": "true"},
                {"name": "STROKESENSE_JOB_ID", "value": job_id},
                {"name": "STROKESENSE_USER_HASH", "value": owner_hash},
                {"name": "STROKESENSE_S3_BUCKET", "value": config.bucket},
                {"name": "STROKESENSE_INPUT_KEY", "value": original},
                {"name": "STROKESENSE_REPORT_KEY", "value": report},
                {"name": "STROKESENSE_GPU_TIMEOUT_SECONDS", "value": str(MAX_GPU_RUNTIME_SECONDS)},
            ],
        }]},
    }


def enqueue_paid_analysis(
    service: AwsBackend, user_id: str, job_id: str,
    *, sqs: Any, queue_url: str, enabled: bool = False,
) -> dict[str, Any]:
    """Reserve the already-credited upload for a durable one-job FIFO message.

    Not callable via the public API yet. If SQS fails after the state changes,
    the job remains 'gpu_queued' for an outbox/reconciler to retry safely.
    """
    if not enabled or not service.cfg.paid_gpu_enabled or not service.cfg.gpu_dispatch_ready:
        raise ApiError(503, "gpu_dispatch_disabled", "Paid GPU dispatch is not enabled")
    if not isinstance(queue_url, str) or not queue_url.endswith(".fifo"):
        raise ApiError(503, "gpu_queue_not_configured", "A dedicated FIFO queue is required")
    record = service._record(job_id, user_id)
    _keys(record)
    require_paid_membership(service, user_id)
    if record.get("status") != "uploaded":
        raise ApiError(409, "invalid_state", "The paid upload is not ready")
    now = service._now()
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)},
            UpdateExpression=("SET #state = :pending, updated_at = :updated, "
                              "expires_at = :due, gpu_queued_at = :queued_epoch"),
            ConditionExpression="user_id = :owner AND #state = :uploaded AND tier = :paid",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={
                ":owner": _s(user_id), ":uploaded": _s("uploaded"), ":paid": _s("paid"),
                ":pending": _s("gpu_queued"), ":updated": _s(datetime.fromtimestamp(
                    now, timezone.utc).isoformat(timespec="seconds")),
                ":due": _n(now + 60), ":queued_epoch": _n(now),
            },
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(409, "job_changed", "Paid analysis is already queued or changed") from exc
        raise
    try:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"v": 1, "job_id": job_id}, separators=(",", ":")),
            MessageGroupId="single-paid-gpu",
            MessageDeduplicationId=job_id,
        )
    except Exception:
        # Do not undo the enqueue state: send may have succeeded before timeout.
        return {"job_id": job_id, "status": "gpu_queued", "dispatch_confirmed": False}
    return {"job_id": job_id, "status": "gpu_queued", "dispatch_confirmed": True}


def dispatch_gpu_task(
    service: AwsBackend, ecs: Any, config: GpuDispatcherConfig, job_id: str,
) -> dict[str, str]:
    """Claim one GPU task slot, verify ECS GPU task and launch idempotently.

    A later GPU lifecycle reconciler must release the lock after ECS stops and
    atomically settle the reserved credit. This dispatcher is NOT connected
    to a Lambda trigger until that reconciler exists.
    """
    config.check()
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ApiError(400, "invalid_job", "GPU job ID is invalid")
    result = service.ddb.get_item(
        TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True)
    record = _decode(result["Item"]) if "Item" in result else {}
    _keys(record)
    if record.get("status") == "gpu_submitted" and record.get("ecs_task_arn"):
        return {"job_id": job_id, "ecs_task_arn": record["ecs_task_arn"]}
    if record.get("status") in ("succeeded", "failed"):
        # An earlier outbox replay might arrive after successful settlement.
        # Acknowledge safely instead of poisoning the FIFO group/DLQ.
        return {"job_id": job_id, "status": record["status"]}
    if record.get("status") not in ("gpu_queued", "gpu_dispatching"):
        raise ApiError(409, "invalid_state", "GPU job is not ready for dispatch")
    now = service._now()
    if record["status"] == "gpu_dispatching":
        started = record.get("gpu_dispatch_started_at")
        if type(started) is not int or now < started or now - started >= 23 * 3600:
            # ECS RunTask clientToken idempotency lasts for at most 24h.
            # Never repeat an old unknown launch after that window.
            raise ApiError(409, "gpu_dispatch_manual_review", "GPU task launch requires manual review")
    _gpu_task_is_approved(ecs, config)
    # One running task globally, even across Lambda retries or concurrent
    # messages. A stale lock is NEVER stolen while the old task might
    # still be billable. Only confirmed ECS STOPPED reconciliation releases it.
    try:
        service.ddb.update_item(
            TableName=service.cfg.users_table,
            Key={"user_id": _s(GPU_LOCK_ID)},
            UpdateExpression="SET active_job = :job, active_job_expires_at = :expiry",
            ConditionExpression="attribute_not_exists(active_job) OR active_job = :job",
            ExpressionAttributeValues={":job": _s(job_id), ":expiry": _n(now + 7200), ":now": _n(now)},
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(429, "gpu_capacity_busy", "The GPU processing slot is occupied") from exc
        raise
    if record["status"] == "gpu_queued":
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)},
            UpdateExpression="SET #state = :dispatching, gpu_dispatch_started_at = :started",
            ConditionExpression="user_id = :owner AND #state = :queued AND tier = :paid",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={
                ":owner": _s(record["user_id"]), ":queued": _s("gpu_queued"),
                ":dispatching": _s("gpu_dispatching"), ":paid": _s("paid"),
                ":started": _n(now),
            },
        )
    task = ecs.run_task(**_run_request(config, record))
    tasks = task.get("tasks") or []
    if task.get("failures") or len(tasks) != 1 or not tasks[0].get("taskArn"):
        raise ApiError(503, "gpu_task_rejected", "GPU scheduler rejected the task")
    arn = tasks[0]["taskArn"]
    service.ddb.update_item(
        TableName=service.cfg.jobs_table,
        Key={"job_id": _s(job_id)},
        UpdateExpression=(
            "SET #state = :running, ecs_task_arn = :arn, expires_at = :poll_due, "
            "gpu_task_deadline_epoch = :deadline"
        ),
        ConditionExpression="user_id = :owner AND #state = :dispatching AND tier = :paid",
        ExpressionAttributeNames={"#state": "status"},
        ExpressionAttributeValues={
            ":owner": _s(record["user_id"]), ":dispatching": _s("gpu_dispatching"),
            ":running": _s("gpu_submitted"), ":paid": _s("paid"),
            ":arn": _s(arn), ":poll_due": _n(now + 60),
            ":deadline": _n(now + MAX_GPU_RUNTIME_SECONDS + 600),
        },
    )
    return {"job_id": job_id, "ecs_task_arn": arn}
