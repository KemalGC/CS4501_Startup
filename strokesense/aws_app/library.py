"""Owner-scoped analysis history and consent-gated, audited admin review.

The backend receives Cognito claims only from API Gateway's JWT authorizer.
Browser-provided email addresses, group names and user IDs are never trusted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .core import ApiError, AwsBackend, CONTENT_TYPES, _decode, _is_conditional, _item, _n, _s, _user_hash, _safe_filename, aws_error_code


_JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
_ISO_TIME = re.compile(r"[0-9TZ+:.\-]{10,40}\Z")
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 30
ADMIN_PREVIEW_TTL_SECONDS = 60
MAX_ARTIFACT_MANIFEST_BYTES = 64 * 1024
ADMIN_GROUP = "strokesense-admin"


def _safe_number(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value < 2**53 else None


def _utc_from_millis(value: Any) -> str | None:
    millis = _safe_number(value)
    if not millis:
        return None
    return datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat(timespec="seconds")


def public_job_view(record: dict[str, Any], now: int) -> dict[str, Any]:
    """Explicit allowlist. Never return S3 object keys or uploader IDs."""
    status = record.get("status", "unknown")
    report_expires = _safe_number(record.get("report_expires_at"))
    video_expires = _safe_number(record.get("video_expires_at"))
    duration = _safe_number(record.get("video_duration_ms"))
    original_window = status not in ("uploading", "aborted") and video_expires is not None and now < video_expires
    annotated_window = status == "succeeded" and record.get("tier") == "free" and report_expires is not None and now < report_expires
    return {
        "job_id": record.get("job_id"),
        "video_id": record.get("job_id"),
        "filename": record.get("filename") or "Rowing video",
        "tier": record.get("tier", "free"),
        "status": status,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "uploaded_at": record.get("uploaded_at"),
        "submitted_at": record.get("submitted_at"),
        "completed_at": _utc_from_millis(record.get("batch_stopped_at_ms")) or (
            record.get("updated_at") if status in ("succeeded", "failed", "aborted") else None
        ),
        "size_bytes": record.get("size_bytes"),
        "duration_seconds": round(duration / 1000, 3) if duration is not None else None,
        "analysis_wall_ms": _safe_number(record.get("analysis_wall_ms")),
        "cpu_time_ms": _safe_number(record.get("cpu_time_ms")),
        "queue_wait_ms": _safe_number(record.get("queue_wait_ms")),
        "batch_run_ms": _safe_number(record.get("batch_run_ms")),
        "batch_created_at_ms": _safe_number(record.get("batch_created_at_ms")),
        "batch_started_at_ms": _safe_number(record.get("batch_started_at_ms")),
        "batch_stopped_at_ms": _safe_number(record.get("batch_stopped_at_ms")),
        "report_expires_at": report_expires,
        "report_available": status == "succeeded" and report_expires is not None and now < report_expires,
        "video_expires_at": video_expires,
        # Eligibility for either raw or annotated media, not proof a file is
        # present in S3. Admin/owner media presign must check the object.
        "video_available": original_window or annotated_window,
        "original_video_available": original_window,
        "annotated_video_may_be_available": annotated_window,
        "allow_admin_review": record.get("allow_admin_review") is True,
        "history_expires_at": _safe_number(record.get("ttl_epoch")),
    }


def batch_timings(detail: dict[str, Any]) -> dict[str, int]:
    """Batch timestamps are UTC milliseconds, NOT measured CPU time."""
    timings = {}
    for aws_key, result_key in (
        ("createdAt", "batch_created_at_ms"),
        ("startedAt", "batch_started_at_ms"),
        ("stoppedAt", "batch_stopped_at_ms"),
    ):
        value = _safe_number(detail.get(aws_key))
        if value is not None and value > 0:
            timings[result_key] = value
    queued = timings.get("batch_created_at_ms")
    started = timings.get("batch_started_at_ms")
    stopped = timings.get("batch_stopped_at_ms")
    if queued and started and started >= queued:
        timings["queue_wait_ms"] = started - queued
    if started and stopped and stopped >= started:
        timings["batch_run_ms"] = stopped - started
    return timings


def load_worker_timings(service: AwsBackend, record: dict[str, Any]) -> dict[str, int]:
    """Best-effort tiny worker sidecar, avoids reading 32 MB HTML reports."""
    key = str(record.get("report_key", ""))
    job_id = str(record.get("job_id", ""))
    if not key.endswith("/report.json") or not _JOB_ID.fullmatch(job_id):
        return {}
    try:
        response = service.s3.get_object(Bucket=service.cfg.bucket, Key=key[:-len("report.json")] + "runtime-metrics.json")
        stream = response["Body"]
        try:
            raw = stream.read(4097)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
    except Exception:
        # Old workers may not have a sidecar, and metrics must never prevent
        # an otherwise valid finished job from settling the user's quota.
        return {}
    if not isinstance(raw, bytes) or len(raw) > 4096:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError):
        return {}
    if not isinstance(parsed, dict) or parsed.get("job_id") != job_id:
        return {}
    fields = ("analysis_wall_ms", "cpu_time_ms", "worker_wall_ms", "video_duration_ms", "frames_processed")
    return {key: value for key in fields if (value := _safe_number(parsed.get(key))) is not None}


def _page_limit(query: dict[str, Any]) -> int:
    raw = query.get("limit", str(DEFAULT_PAGE_SIZE))
    if not isinstance(raw, str) or not raw.isdigit() or not 1 <= int(raw) <= MAX_PAGE_SIZE:
        raise ApiError(400, "invalid_page_size", f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return int(raw)


def _decode_cursor(token: Any, scope: str, partition: str, partition_value: str) -> dict[str, Any] | None:
    if not token:
        return None
    if not isinstance(token, str) or len(token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ApiError(400, "invalid_cursor", "Invalid history pagination cursor")
    try:
        contents = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        decoded = json.loads(contents)
    except (ValueError, UnicodeError):
        raise ApiError(400, "invalid_cursor", "Invalid history pagination cursor") from None
    if not isinstance(decoded, dict) or decoded.get("v") != 1 or decoded.get("scope") != scope:
        raise ApiError(400, "invalid_cursor", "History cursor does not belong to this account")
    key = decoded.get("key")
    if not isinstance(key, dict) or set(key) != {partition, "created_at", "job_id"}:
        raise ApiError(400, "invalid_cursor", "Invalid history pagination cursor")
    if (key[partition] != {"S": partition_value}
            or not isinstance(key["job_id"], dict)
            or not isinstance(key["created_at"], dict)):
        raise ApiError(400, "invalid_cursor", "History cursor does not belong to this account")
    job_id, created = key["job_id"].get("S"), key["created_at"].get("S")
    if (not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id)
            or not isinstance(created, str) or not _ISO_TIME.fullmatch(created)):
        raise ApiError(400, "invalid_cursor", "Invalid history pagination cursor")
    return key


def _encode_cursor(key: Any, scope: str) -> str | None:
    if not isinstance(key, dict) or not key:
        return None
    raw = json.dumps({"v": 1, "scope": scope, "key": key}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _list_index(
    service: AwsBackend, *, index: str, partition: str, value: str,
    scope: str, query: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(query, dict):
        raise ApiError(400, "invalid_request", "History query must be an object")
    request = {
        "TableName": service.cfg.jobs_table,
        "IndexName": index,
        "KeyConditionExpression": f"{partition} = :partition",
        "ExpressionAttributeValues": {":partition": _s(value)},
        "Limit": _page_limit(query),
        "ScanIndexForward": False,
    }
    cursor = _decode_cursor(query.get("cursor"), scope, partition, value)
    if cursor:
        request["ExclusiveStartKey"] = cursor
    page = service.ddb.query(**request)
    jobs = [public_job_view(_decode(raw), service._now()) for raw in page.get("Items", [])]
    return {"jobs": jobs, "next_cursor": _encode_cursor(page.get("LastEvaluatedKey"), scope)}


def list_owner_jobs(service: AwsBackend, user_id: str, query: dict[str, Any]) -> dict[str, Any]:
    page = _list_index(
        service, index="user_id-created_at-index", partition="user_id",
        value=user_id, scope=f"owner:{user_id}", query=query,
    )
    # Deleted records can remain in the eventually consistent owner GSI.
    # Strongly re-check before displaying them (or previously shared media).
    visible = []
    for card in page["jobs"]:
        job_id = card.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            continue
        item = service.ddb.get_item(
            TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)},
            ConsistentRead=True,
        )
        current = _decode(item["Item"]) if "Item" in item else {}
        if current.get("user_id") == user_id and current.get("status") != "deleting":
            visible.append(public_job_view(current, service._now()))
    page["jobs"] = visible
    return page


def rename_owned_job(service: AwsBackend, user_id: str, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Change only an owner-visible name, never the underlying S3 object key."""
    if "filename" not in body:
        raise ApiError(400, "invalid_filename", "A new video name is required")
    if body["filename"] is None:
        raise ApiError(400, "invalid_filename", "A new video name is required")
    filename = _safe_filename(body["filename"])
    record = service._record(job_id, user_id)
    if record.get("status") == "deleting":
        raise ApiError(404, "not_found", "This analysis has been deleted")
    timestamp = datetime.fromtimestamp(service._now(), timezone.utc).isoformat(timespec="seconds")
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table,
            Key={"job_id": _s(job_id)},
            UpdateExpression="SET filename = :filename, updated_at = :updated",
            ConditionExpression="user_id = :uid AND attribute_exists(job_id) AND #state <> :deleting",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={
                ":filename": _s(filename), ":updated": _s(timestamp),
                ":uid": _s(user_id), ":deleting": _s("deleting"),
            },
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(404, "not_found", "Video or job not found") from exc
        raise
    return {"job_id": job_id, "filename": filename}


def change_review_consent(service: AwsBackend, user_id: str, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    allowed = body.get("allow_admin_review")
    if type(allowed) is not bool:
        raise ApiError(400, "invalid_consent", "allow_admin_review must be true or false")
    current = service._record(job_id, user_id)  # Strongly consistent owner check.
    if current.get("status") == "deleting":
        raise ApiError(404, "not_found", "This analysis has been deleted")
    values = {
        ":uid": _s(user_id), ":consent": {"BOOL": allowed},
        ":updated": _s(datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ":deleting": _s("deleting"),
    }
    expression = "SET allow_admin_review = :consent, admin_review_decided_at = :updated"
    if allowed:
        expression += ", admin_partition = :opted_in"
        values[":opted_in"] = _s("OPTED_IN")
    else:
        expression += " REMOVE admin_partition"
    try:
        service.ddb.update_item(
            TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)},
            UpdateExpression=expression,
            ConditionExpression="user_id = :uid AND #state <> :deleting",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues=values,
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(404, "not_found", "Video or job not found") from exc
        raise
    return {"job_id": job_id, "allow_admin_review": allowed}


def require_admin(claims: dict[str, Any]) -> str:
    """Require both a signed Cognito group and a configured immutable sub."""
    sub = claims.get("sub")
    approved_subs = {value.strip() for value in os.getenv("ADMIN_COGNITO_SUBS", "").split(",") if value.strip()}
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        try:
            groups = json.loads(groups)
        except ValueError:
            groups = []
    if (not isinstance(sub, str) or not sub or sub not in approved_subs
            or claims.get("token_use") != "access"
            or not isinstance(groups, list) or ADMIN_GROUP not in groups):
        raise ApiError(403, "admin_forbidden", "Administrator permissions are required")
    return sub


def list_review_jobs(service: AwsBackend, query: dict[str, Any]) -> dict[str, Any]:
    page = _list_index(
        service, index="admin_partition-created_at-index", partition="admin_partition",
        value="OPTED_IN", scope="admin-consented", query=query,
    )
    # GSIs are eventually consistent; after revocation an old index entry may
    # remain briefly visible. Recheck each candidate against the strongly
    # consistent base table before exposing even its filename/metadata.
    visible = []
    for card in page["jobs"]:
        job_id = card.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            continue
        item = service.ddb.get_item(TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True)
        current = _decode(item["Item"]) if "Item" in item else {}
        if current.get("allow_admin_review") is True and current.get("admin_partition") == "OPTED_IN":
            visible.append(public_job_view(current, service._now()))
    page["jobs"] = visible
    return page


def admin_video_url(service: AwsBackend, admin_sub: str, job_id: str, request_context: dict[str, Any]) -> dict[str, Any]:
    """Prefer annotated video, then original, after consent check + audit."""
    if not service.cfg.admin_audit_table:
        raise ApiError(503, "audit_unavailable", "Administrator review is not configured")
    response = service.ddb.get_item(TableName=service.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True)
    record = _decode(response["Item"]) if "Item" in response else {}
    owner = record.get("user_id")
    if (not isinstance(owner, str) or not record.get("allow_admin_review")
            or record.get("admin_partition") != "OPTED_IN" or record.get("status") in ("uploading", "aborted")):
        raise ApiError(404, "not_found", "Shared video is not available")
    original_expires = _safe_number(record.get("video_expires_at"))
    expected_key = f"uploads/{_user_hash(owner)}/{job_id}/original{CONTENT_TYPES.get(record.get('content_type'), '')}"
    if not CONTENT_TYPES.get(record.get("content_type")) or record.get("s3_key") != expected_key:
        raise ApiError(409, "invalid_media_record", "Stored video record is invalid")
    now = service._now()
    video_type = "original"
    expires = original_expires
    selected_key = None

    # The annotated report video has its own report-prefix retention. This
    # allows opted-in review after the short original-upload retention expires.
    report_expires = _safe_number(record.get("report_expires_at"))
    expected_report = f"reports/free/{_user_hash(owner)}/{job_id}/report.json"
    if (record.get("status") == "succeeded" and record.get("tier") == "free"
            and record.get("report_key") == expected_report and report_expires and report_expires > now):
        prefix = expected_report[:-len("report.json")]
        try:
            manifest = service.s3.get_object(Bucket=service.cfg.bucket, Key=prefix + "artifacts.json")
        except Exception as exc:
            if aws_error_code(exc) not in ("404", "NoSuchKey", "NotFound") and not isinstance(exc, AttributeError):
                raise
        else:
            stream = manifest.get("Body")
            try:
                if (not isinstance(manifest.get("ContentLength"), int)
                        or manifest["ContentLength"] > MAX_ARTIFACT_MANIFEST_BYTES
                        or stream is None or not callable(getattr(stream, "read", None))):
                    raise ApiError(503, "media_unavailable", "Annotated video manifest is invalid")
                raw = stream.read(MAX_ARTIFACT_MANIFEST_BYTES + 1)
                if not isinstance(raw, bytes) or len(raw) > MAX_ARTIFACT_MANIFEST_BYTES:
                    raise ApiError(503, "media_unavailable", "Annotated video manifest is invalid")
                try:
                    parsed = json.loads(raw)
                except (ValueError, UnicodeError):
                    parsed = {}
                if (isinstance(parsed, dict) and parsed.get("schema_version") == "strokesense-private-artifacts-v1"
                        and parsed.get("video_available") is True):
                    annotated_key = prefix + "annotated.mp4"
                    try:
                        metadata = service.s3.head_object(Bucket=service.cfg.bucket, Key=annotated_key)
                    except Exception as exc:
                        if aws_error_code(exc) not in ("404", "NoSuchKey", "NotFound"):
                            raise
                    else:
                        length = metadata.get("ContentLength")
                        if type(length) is int and 0 < length <= 120 * 1024 * 1024:
                            selected_key = annotated_key
                            expires = report_expires
                            video_type = "annotated"
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

    if selected_key is None:
        if expires is None or expires <= service._now():
            raise ApiError(410, "video_expired", "No retained video is available for review")
        try:
            metadata = service.s3.head_object(Bucket=service.cfg.bucket, Key=expected_key)
        except Exception as exc:
            if aws_error_code(exc) in ("404", "NoSuchKey", "NotFound"):
                raise ApiError(410, "video_expired", "No retained video is available for review") from exc
            raise
        length = metadata.get("ContentLength")
        if type(length) is not int or length <= 0 or length != record.get("size_bytes"):
            raise ApiError(409, "invalid_media_record", "Stored video size does not match its upload record")
        selected_key = expected_key

    lifetime = min(ADMIN_PREVIEW_TTL_SECONDS, expires - service._now())
    signed = service.s3.generate_presigned_url(
        "get_object", Params={"Bucket": service.cfg.bucket, "Key": selected_key},
        ExpiresIn=lifetime, HttpMethod="GET",
    )
    issued = service._now()
    source_ip = str(request_context.get("sourceIp", ""))[:64]
    user_agent = str(request_context.get("userAgent", ""))[:1024]
    event = {
        "audit_id": uuid.uuid4().hex,
        "action": "admin_video_presigned",
        "video_type": video_type,
        "viewer_sub": admin_sub,
        "owner_sub": owner,
        "job_id": job_id,
        "issued_at": datetime.fromtimestamp(issued, timezone.utc).isoformat(timespec="seconds"),
        "source_ip": source_ip,
        "user_agent_sha256": hashlib.sha256(user_agent.encode("utf-8")).hexdigest(),
        "presign_expires_at": issued + lifetime,
        "ttl_epoch": issued + min(365, max(30, int(os.getenv("ADMIN_AUDIT_TTL_DAYS", "90")))) * 86400,
    }
    condition = "user_id = :owner AND allow_admin_review = :yes AND admin_partition = :partition AND #state <> :aborted"
    condition_values = {
        ":owner": _s(owner), ":yes": {"BOOL": True},
        ":partition": _s("OPTED_IN"), ":now": _n(issued),
        ":aborted": _s("aborted"),
    }
    if video_type == "annotated":
        condition += " AND report_expires_at > :now AND #state = :succeeded"
        condition_values[":succeeded"] = _s("succeeded")
    else:
        condition += " AND video_expires_at > :now"
    try:
        service.ddb.transact_write_items(TransactItems=[
            {"ConditionCheck": {
                "TableName": service.cfg.jobs_table, "Key": {"job_id": _s(job_id)},
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {"#state": "status"},
                "ExpressionAttributeValues": condition_values,
            }},
            {"Put": {
                "TableName": service.cfg.admin_audit_table,
                "Item": _item(event),
                "ConditionExpression": "attribute_not_exists(audit_id)",
            }},
        ])
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(403, "consent_revoked", "This video's review consent is no longer active") from exc
        raise ApiError(503, "audit_unavailable", "Administrator review could not be recorded") from exc
    return {"job_id": job_id, "video_url": signed, "video_type": video_type, "expires_in": lifetime, "video_expires_at": expires}
