"""Scheduled, ownership-preserving reconciliation for abandoned AWS analysis jobs.

The public API settles jobs when users poll, but users can close their tabs.
An EventBridge schedule invokes this separate Lambda every 15 minutes to
recover stale upload reservations and settle completed Batch jobs regardless
of whether the browser ever reconnects. All account updates use the same
conditional DynamoDB transactions as the request path.
"""

from __future__ import annotations

import logging
from typing import Any

from .core import ApiError, AwsBackend, Settings, _decode, _n, _s
from .deletion import finish_deletion


LOGGER = logging.getLogger(__name__)
PENDING_STATES = ("uploading", "uploaded", "submitted", "submitting", "deleting")
DEFAULT_PER_STATE_LIMIT = 25


def reconcile_due(service: AwsBackend, *, per_state_limit: int = DEFAULT_PER_STATE_LIMIT) -> dict[str, int]:
    """Examine expired reservations efficiently through a status/expiry GSI.

    The query index is eventually consistent, so re-read each record through
    the base table with ConsistentRead before acting. A concurrent submit or
    poll cannot be charged/refunded twice because _settle/_abort_record share
    conditional account+job transactions.

    `submitting` is *not* automatically refunded. The Batch SubmitJob call
    may have succeeded before persisting batch_job_id; it requires operator
    investigation to avoid a running job processing a refunded upload.
    """
    if per_state_limit < 1 or per_state_limit > 100:
        raise ValueError("per_state_limit must be between 1 and 100")

    now = service._now()
    counts = {
        "examined": 0,
        "aborted": 0,
        "failed": 0,
        "succeeded": 0,
        "deleted": 0,
        "pending": 0,
        "manual_review": 0,
        "errors": 0,
        "truncated_states": 0,
    }
    for state in PENDING_STATES:
        remaining = per_state_limit
        request: dict[str, Any] = {
            "TableName": service.cfg.jobs_table,
            "IndexName": "status-expires_at-index",
            "KeyConditionExpression": "#state = :state AND expires_at < :now",
            "ExpressionAttributeNames": {"#state": "status"},
            "ExpressionAttributeValues": {":state": _s(state), ":now": _n(now)},
        }
        while remaining > 0:
            request["Limit"] = min(remaining, 25)
            page = service.ddb.query(**request)
            for raw in page.get("Items", []):
                counts["examined"] += 1
                remaining -= 1
                indexed_record = _decode(raw)
                job_id = indexed_record.get("job_id")
                user_id = indexed_record.get("user_id")
                if not isinstance(job_id, str) or not isinstance(user_id, str):
                    counts["errors"] += 1
                    LOGGER.error("A due reconciliation index entry has invalid keys")
                    continue
                try:
                    # Verify the current state before consuming an old index
                    # entry; the original upload might have just started a job.
                    try:
                        record = service._record(job_id, user_id)
                    except ApiError as exc:
                        # A concurrent owner deletion may have removed the
                        # record, while the status GSI still has a stale row.
                        if state == "deleting" and exc.status == 404:
                            continue
                        raise
                    if record.get("status") != state or int(record.get("expires_at", 0)) >= now:
                        continue
                    if state == "deleting":
                        finish_deletion(service, record)
                        counts["deleted"] += 1
                    elif state in ("uploading", "uploaded"):
                        if service._abort_record(record):
                            counts["aborted"] += 1
                    elif state == "submitted":
                        if not record.get("batch_job_id"):
                            counts["manual_review"] += 1
                            LOGGER.warning("Submitted job has no Batch ID: job_id=%s", job_id)
                            continue
                        batch_state = service._batch_status(record)
                        if batch_state == "FAILED":
                            service._settle(record, succeeded=False)
                            counts["failed"] += 1
                        elif batch_state == "SUCCEEDED":
                            report_exists = service._report_exists(record)
                            service._settle(record, succeeded=report_exists)
                            counts["succeeded" if report_exists else "failed"] += 1
                        else:
                            # Includes RUNNING and the conservative case where
                            # AWS Batch has not returned an authoritative job.
                            counts["pending"] += 1
                    else:
                        counts["manual_review"] += 1
                        LOGGER.warning("Stale submitting job requires manual review: job_id=%s", job_id)
                except Exception:
                    counts["errors"] += 1
                    LOGGER.exception("Failed to reconcile job_id=%s; quota state is unchanged", job_id)

            start_key = page.get("LastEvaluatedKey")
            if not start_key:
                break
            if remaining == 0:
                counts["truncated_states"] += 1
                break
            request["ExclusiveStartKey"] = start_key
    return counts


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    """Scheduled-only Lambda entrypoint. No public HTTP route exposes this."""
    if event.get("source") != "aws.events":
        raise ValueError("Only scheduled EventBridge events are accepted")

    import boto3

    settings = Settings.from_env()
    service = AwsBackend(
        settings,
        dynamodb=boto3.client("dynamodb"),
        s3=boto3.client("s3"),
        batch=boto3.client("batch"),
    )
    stats = reconcile_due(service)
    LOGGER.info("Reconciliation result: %s", stats)
    # Surface both operational errors and ambiguous SubmitJob transitions
    # through the Lambda Errors alarm. An ambiguous submission must be reviewed
    # by an operator before refunding, or a live job could become free.
    # Retried runs are safe because all quota changes are conditional.
    if stats["errors"] or stats["manual_review"]:
        raise RuntimeError(
            f"Reconciliation requires attention: {stats['errors']} error(s), "
            f"{stats['manual_review']} ambiguous submission(s)"
        )
    return stats
