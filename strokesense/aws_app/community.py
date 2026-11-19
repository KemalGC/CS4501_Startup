"""Explicit owner-controlled community video sharing.

Admin-review consent is intentionally unrelated to community publication.
All S3 objects remain private; anonymous viewers receive only a short-lived
signed link to an owner-published *annotated* clip, never the original upload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .core import ApiError, AwsBackend, _decode, _is_conditional, _n, _s, _user_hash, aws_error_code
from .library import _JOB_ID, _decode_cursor, _encode_cursor, _page_limit, _safe_number

COMMUNITY_PARTITION = "PUBLIC"
COMMUNITY_VIDEO_TTL_SECONDS = 60
MAX_VIDEO_BYTES = 120 * 1024 * 1024


def _annotated_key(record: dict[str, Any]) -> str | None:
    owner, job_id = record.get("user_id"), record.get("job_id")
    if (not isinstance(owner, str) or not owner or not isinstance(job_id, str)
            or not _JOB_ID.fullmatch(job_id) or record.get("tier") != "free"):
        return None
    prefix = f"reports/free/{_user_hash(owner)}/{job_id}/"
    if record.get("report_key") != prefix + "report.json":
        return None
    return prefix + "annotated.mp4"


def _published(record: dict[str, Any], now: int) -> bool:
    expiry = _safe_number(record.get("report_expires_at"))
    return (
        record.get("community_shared") is True
        and record.get("community_partition") == COMMUNITY_PARTITION
        and record.get("status") == "succeeded"
        and expiry is not None and expiry > now
        and _annotated_key(record) is not None
    )


def _media_exists(service: AwsBackend, key: str) -> bool:
    try:
        response = service.s3.head_object(Bucket=service.cfg.bucket, Key=key)
    except Exception as exc:
        if aws_error_code(exc) in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    size = response.get("ContentLength")
    return type(size) is int and 0 < size <= MAX_VIDEO_BYTES


def change_community_visibility(
    service: AwsBackend, user_id: str, job_id: str, body: dict[str, Any],
) -> dict[str, Any]:
    """Publish/unpublish one completed owner's annotated MP4, never the raw clip."""
    enabled = body.get("public")
    if type(enabled) is not bool:
        raise ApiError(400, "invalid_visibility", "public must be true or false")
    if not _JOB_ID.fullmatch(job_id):
        raise ApiError(404, "not_found", "Video or job not found")
    record = service._record(job_id, user_id)  # Strongly consistent owner check.
    now = service._now()
    timestamp = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
    values: dict[str, Any] = {
        ":uid": _s(user_id), ":visible": {"BOOL": enabled}, ":updated": _s(timestamp),
    }
    expression = "SET community_shared = :visible, community_updated_at = :updated"
    kwargs: dict[str, Any] = {}
    if enabled:
        key = _annotated_key(record)
        expiry = _safe_number(record.get("report_expires_at"))
        if (record.get("status") != "succeeded" or expiry is None or expiry <= now or not key):
            raise ApiError(409, "not_ready", "Only an available completed free analysis can be made public")
        if not _media_exists(service, key):
            raise ApiError(409, "video_unavailable", "No annotated video is available to publish")
        expression += ", community_partition = :partition, community_published_at = :updated"
        values.update({
            ":partition": _s(COMMUNITY_PARTITION), ":succeeded": _s("succeeded"),
            ":now": _n(now), ":report": _s(record["report_key"]),
        })
        kwargs = {
            "ConditionExpression": "user_id = :uid AND #state = :succeeded AND report_expires_at > :now AND report_key = :report",
            "ExpressionAttributeNames": {"#state": "status"},
        }
    else:
        expression += " REMOVE community_partition, community_published_at"
        kwargs = {"ConditionExpression": "user_id = :uid"}
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
            **kwargs,
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(409 if enabled else 404, "visibility_changed",
                           "Video is no longer eligible for this visibility change") from exc
        raise
    return {"job_id": job_id, "public": enabled}


def list_community_videos(service: AwsBackend, query: dict[str, Any]) -> dict[str, Any]:
    """Anonymous browse, but no usernames, private filenames or S3 keys."""
    if not isinstance(query, dict):
        raise ApiError(400, "invalid_request", "Community query must be an object")
    # Use a sparse GSI; never scan unrelated private jobs.
    normalized = {"limit": query.get("limit", "12"), "cursor": query.get("cursor")}
    request: dict[str, Any] = {
        "TableName": service.cfg.jobs_table,
        "IndexName": "community_partition-created_at-index",
        "KeyConditionExpression": "community_partition = :partition",
        "ExpressionAttributeValues": {":partition": _s(COMMUNITY_PARTITION)},
        "Limit": _page_limit(normalized),
        "ScanIndexForward": False,
    }
    cursor = _decode_cursor(normalized["cursor"], "public-community", "community_partition", COMMUNITY_PARTITION)
    if cursor:
        request["ExclusiveStartKey"] = cursor
    page = service.ddb.query(**request)
    now = service._now()
    visible = []
    for raw in page.get("Items", []):
        candidate = _decode(raw)
        job_id = candidate.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            continue
        # A stale GSI entry after unpublishing cannot expose even metadata.
        result = service.ddb.get_item(
            TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True,
        )
        record = _decode(result["Item"]) if "Item" in result else {}
        if not _published(record, now) or record.get("job_id") != job_id:
            continue
        duration = _safe_number(record.get("video_duration_ms"))
        visible.append({
            "job_id": job_id,
            "title": "Community rowing session",
            "created_at": record.get("created_at"),
            "published_at": record.get("community_published_at"),
            "duration_seconds": round(duration / 1000, 3) if duration is not None else None,
            "expires_at": record["report_expires_at"],
        })
    return {"videos": visible, "next_cursor": _encode_cursor(page.get("LastEvaluatedKey"), "public-community")}


def community_video_url(service: AwsBackend, job_id: str) -> dict[str, Any]:
    """Anonymous short-lived playback link, with fresh conditional consent."""
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ApiError(404, "not_found", "Public video not found")
    result = service.ddb.get_item(
        TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True,
    )
    record = _decode(result["Item"]) if "Item" in result else {}
    now = service._now()
    if not _published(record, now):
        raise ApiError(404, "not_found", "Public video not found")
    key = _annotated_key(record)
    if key is None or not _media_exists(service, key):
        raise ApiError(410, "video_expired", "This community video is no longer available")
    # A conditional read at the signing boundary closes stale-index races.
    # Previously issued presigned URLs may remain valid for at most 60 seconds.
    condition = (
        "user_id = :owner AND community_shared = :yes AND "
        "community_partition = :partition AND #state = :succeeded AND "
        "report_expires_at > :now AND report_key = :report"
    )
    try:
        service.ddb.transact_write_items(TransactItems=[{
            "ConditionCheck": {
                "TableName": service.cfg.jobs_table,
                "Key": {"job_id": _s(job_id)},
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {"#state": "status"},
                "ExpressionAttributeValues": {
                    ":owner": _s(record["user_id"]), ":yes": {"BOOL": True},
                    ":partition": _s(COMMUNITY_PARTITION), ":succeeded": _s("succeeded"),
                    ":now": _n(now), ":report": _s(record["report_key"]),
                },
            },
        }])
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(404, "not_found", "This community video is no longer shared") from exc
        raise
    expires_in = min(COMMUNITY_VIDEO_TTL_SECONDS, record["report_expires_at"] - service._now())
    if expires_in <= 0:
        raise ApiError(410, "video_expired", "This community video has expired")
    url = service.s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": service.cfg.bucket, "Key": key},
        ExpiresIn=expires_in, HttpMethod="GET",
    )
    return {"job_id": job_id, "video_url": url, "expires_in": expires_in, "video_type": "annotated"}
