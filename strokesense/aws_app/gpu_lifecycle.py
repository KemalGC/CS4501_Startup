"""Paid GPU ECS lifecycle and one-time credit settlement (not yet deployed).

Only an authoritative STOPPED ECS task may consume/refund the reserved paid
credit. Ambiguous or missing task state leaves the reservation untouched.
"""
from __future__ import annotations

from typing import Any

from .core import ApiError, AwsBackend, _decode, _is_conditional, _s
from .gpu_dispatcher import GpuDispatcherConfig, GPU_LOCK_ID, _keys


def release_gpu_slot(service: AwsBackend, job_id: str) -> None:
    """Release only a lock currently owned by this completed job."""
    try:
        service.ddb.update_item(
            TableName=service.cfg.users_table,
            Key={"user_id": _s(GPU_LOCK_ID)},
            UpdateExpression="REMOVE active_job, active_job_expires_at",
            ConditionExpression="active_job = :job",
            ExpressionAttributeValues={":job": _s(job_id)},
        )
    except Exception as exc:
        if not _is_conditional(exc):
            raise  # The reconciler will retry; do not obscure a real outage.


def reconcile_gpu_job(service: AwsBackend, ecs: Any, config: GpuDispatcherConfig, job_id: str) -> dict[str, str]:
    """Settle once, recheck owner/task identity, and free capacity after STOPPED."""
    config.check()
    response = service.ddb.get_item(
        TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True,
    )
    record = _decode(response["Item"]) if "Item" in response else {}
    _keys(record)
    status = record.get("status")
    if status in ("succeeded", "failed"):
        # A previous settlement may have succeeded before releasing the slot.
        release_gpu_slot(service, job_id)
        return {"job_id": job_id, "status": status}
    if status != "gpu_submitted":
        raise ApiError(409, "invalid_state", "GPU analysis has not yet been submitted")
    arn = record.get("ecs_task_arn")
    if not isinstance(arn, str) or not arn.startswith("arn:aws:ecs:") or len(arn) > 512:
        raise ApiError(409, "gpu_task_unknown", "GPU task identity is unavailable")
    result = ecs.describe_tasks(cluster=config.cluster, tasks=[arn])
    if result.get("failures"):
        raise ApiError(503, "gpu_task_unknown", "GPU task state is unavailable")
    tasks = result.get("tasks") or []
    if len(tasks) != 1 or tasks[0].get("taskArn") != arn:
        raise ApiError(503, "gpu_task_unknown", "GPU task state is unavailable")
    state = tasks[0].get("lastStatus")
    if state != "STOPPED":
        return {"job_id": job_id, "status": "gpu_submitted"}
    containers = tasks[0].get("containers") or []
    matching = [container for container in containers if container.get("name") == config.worker_container]
    if len(matching) != 1 or type(matching[0].get("exitCode")) is not int:
        # ECS STOPPED does not necessarily mean worker completion is known.
        raise ApiError(503, "gpu_exit_unknown", "GPU worker exit status is unavailable")
    succeeded = matching[0]["exitCode"] == 0
    if succeeded:
        # The report is the worker's final successful S3 write.
        succeeded = service._report_exists(record)
    operation = "consume" if succeeded else "refund"
    destination = "succeeded" if succeeded else "failed"
    try:
        service._quota_transaction(record, operation, next_state=destination)
    except Exception as exc:
        if not _is_conditional(exc):
            raise
        current = service._record(job_id, record["user_id"])
        if current.get("status") not in ("succeeded", "failed"):
            raise
        destination = current["status"]
    release_gpu_slot(service, job_id)
    return {"job_id": job_id, "status": destination}
