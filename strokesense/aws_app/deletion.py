"""Owner-authorized, retryable deletion of completed StrokeSense analyses.

Deleting never refunds a completed analysis or changes global Batch counts.
The job becomes inaccessible before any S3 cleanup begins; the scheduled
reconciler retries interrupted deletions. Object names are derived from the
verified Cognito owner, not supplied by a browser or a report manifest.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from .core import ApiError, AwsBackend, CONTENT_TYPES, _decode, _is_conditional, _n, _s, _user_hash

LOGGER = logging.getLogger(__name__)
JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
DELETABLE = frozenset(("succeeded", "failed", "aborted"))
MAX_DELETE_PAGES = 16
S3_BATCH_SIZE = 250
DELETION_TOMBSTONE_SECONDS = 8 * 86400


def _media_keys(record: dict[str, Any], owner: str, job_id: str) -> tuple[str, str]:
    """Reject corrupt records instead of accepting user-controlled S3 paths."""
    suffix = CONTENT_TYPES.get(record.get("content_type"))
    tier = record.get("tier")
    if not suffix or tier not in ("free", "paid") or record.get("job_id") != job_id:
        raise ApiError(409, "invalid_media_record", "Stored analysis metadata is invalid")
    digest = _user_hash(owner)
    source_key = f"uploads/{digest}/{job_id}/original{suffix}"
    report_prefix = f"reports/{tier}/{digest}/{job_id}/"
    if record.get("s3_key") != source_key or record.get("report_key") != report_prefix + "report.json":
        raise ApiError(409, "invalid_media_record", "Stored analysis paths do not match this account")
    return source_key, report_prefix


def finish_deletion(service: AwsBackend, record: dict[str, Any]) -> None:
    """Idempotent cleanup, called by the API and again by the 15-min reconciler."""
    job_id = record.get("job_id")
    owner = record.get("user_id")
    if (not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id)
            or not isinstance(owner, str) or not owner or record.get("status") != "deleting"):
        raise ApiError(409, "invalid_state", "Analysis is not ready for deletion")
    original_key, report_prefix = _media_keys(record, owner, job_id)
    service.s3.delete_object(Bucket=service.cfg.bucket, Key=original_key)

    # The worker emits a bounded annotated video, frames and two small JSON
    # sidecars. Always derive the whole per-job report prefix server-side;
    # never accept a prefix from request JSON or a mutable manifest.
    for _ in range(MAX_DELETE_PAGES):
        page = service.s3.list_objects_v2(
            Bucket=service.cfg.bucket, Prefix=report_prefix, MaxKeys=S3_BATCH_SIZE,
        )
        objects = page.get("Contents") or []
        if not objects:
            if page.get("IsTruncated"):
                raise RuntimeError("S3 returned a truncated empty report listing")
            break
        keys = [obj.get("Key") for obj in objects]
        if (len(keys) > S3_BATCH_SIZE or
                any(not isinstance(key, str) or not key.startswith(report_prefix)
                    or key == report_prefix for key in keys)):
            raise ApiError(503, "deletion_unavailable", "The stored report listing is invalid")
        result = service.s3.delete_objects(
            Bucket=service.cfg.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        if result.get("Errors"):
            raise RuntimeError("S3 rejected one or more private report deletions")
    else:
        raise RuntimeError("S3 report directory exceeded the deletion page limit")

    try:
        service.ddb.delete_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)},
            ConditionExpression="user_id = :uid AND #state = :deleting",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":uid": _s(owner), ":deleting": _s("deleting")},
        )
    except Exception as exc:
        if not _is_conditional(exc):
            raise
        # Another identical deletion may have finished at the same time.
        existing = service.ddb.get_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)}, ConsistentRead=True,
        )
        if existing.get("Item"):
            raise


def delete_owned_analysis(service: AwsBackend, user_id: str, job_id: str) -> dict[str, Any]:
    """Mark inaccessible first, then remove all owned S3 media and the record."""
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ApiError(404, "not_found", "Analysis not found")
    record = service._record(job_id, user_id)
    state = record.get("status")
    if state not in DELETABLE and state != "deleting":
        raise ApiError(409, "analysis_in_progress",
                       "An analysis must finish before you can permanently delete it")

    _media_keys(record, user_id, job_id)
    if state != "deleting":
        now = service._now()
        stamp = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
        try:
            service.ddb.update_item(
                TableName=service.cfg.jobs_table,
                Key={"job_id": _s(job_id)},
                UpdateExpression=(
                    "SET #state = :deleting, updated_at = :updated, "
                    "expires_at = :due, ttl_epoch = :ttl, "
                    "allow_admin_review = :no, community_shared = :no "
                    "REMOVE admin_partition, community_partition"
                ),
                ConditionExpression=(
                    "user_id = :uid AND #state IN (:succeeded, :failed, :aborted)"
                ),
                ExpressionAttributeNames={"#state": "status"},
                ExpressionAttributeValues={
                    ":uid": _s(user_id), ":succeeded": _s("succeeded"),
                    ":failed": _s("failed"), ":aborted": _s("aborted"),
                    ":deleting": _s("deleting"), ":updated": _s(stamp),
                    ":due": _n(now - 1),
                    ":ttl": _n(now + DELETION_TOMBSTONE_SECONDS),
                    ":no": {"BOOL": False},
                },
            )
        except Exception as exc:
            if not _is_conditional(exc):
                raise
            record = service._record(job_id, user_id)
            if record.get("status") != "deleting":
                raise ApiError(409, "analysis_changed", "Analysis state changed") from exc
        else:
            record["status"] = "deleting"
            record["allow_admin_review"] = False
            record["community_shared"] = False

    try:
        finish_deletion(service, record)
    except Exception:
        # The visibility change is already committed. The scheduled Lambda
        # retries without user interaction, and eventual bucket lifecycle
        # deletion is a further safety net. Do not claim cleanup succeeded.
        LOGGER.exception("Deferred private media deletion for job %s", job_id)
        return {"job_id": job_id, "status": "deleting", "message": "Removal is pending AWS cleanup"}
    return {"job_id": job_id, "status": "deleted"}
