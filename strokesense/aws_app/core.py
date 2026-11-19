"""AWS upload, quota, and analysis state management.

All quota transitions are DynamoDB transactions against the account and upload
record. Free usage is reserved at upload creation, consumed only after a real
Batch success with an existing report, and refunded on failure/abort. Paid
credits use the same reservation discipline but are disabled until billing is
explicitly configured.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


FREE_BYTES = 300_000_000
FREE_VIDEO_BYTES = 100_000_000
PAID_VIDEO_BYTES = 750_000_000
PART_BYTES = 8 * 1024 * 1024
UPLOAD_TTL_SECONDS = 60 * 60
PRESIGN_TTL_SECONDS = 15 * 60
FREE_REPORT_TTL_SECONDS = 72 * 60 * 60
PAID_REPORT_TTL_SECONDS = 30 * 24 * 60 * 60
CONTENT_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
ETAG_RE = re.compile(r'^[^\x00-\x1f\x7f]{1,256}$')
LOGGER = logging.getLogger(__name__)
TERMINAL_RECORD_GRACE_SECONDS = 7 * 24 * 60 * 60
# These are global admission limits, not per-user allowances. Every attempted
# Batch submission consumes one slot, including failed/ambiguous submissions,
# because a network error does not prove AWS declined to start the paid job.
DEFAULT_CPU_GLOBAL_DAILY_LIMIT = 5
DEFAULT_CPU_GLOBAL_MONTHLY_LIMIT = 50


class ApiError(Exception):
    """A safe, structured HTTP error (never contains AWS internals)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ApiError(400, "invalid_request", f"{label} must be a positive integer")
    return value


def aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", ""))
    return ""


def _is_conditional(exc: Exception) -> bool:
    code = aws_error_code(exc)
    if code == "ConditionalCheckFailedException":
        return True
    if code == "TransactionCanceledException":
        response = getattr(exc, "response", {})
        return any(reason.get("Code") == "ConditionalCheckFailed" for reason in response.get("CancellationReasons", []))
    return False


def _s(value: Any) -> dict[str, str]:
    return {"S": str(value)}


def _n(value: int) -> dict[str, str]:
    return {"N": str(int(value))}


def _item(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(value, bool):
            result[key] = {"BOOL": value}  # type: ignore[assignment]
        elif isinstance(value, int):
            result[key] = _n(value)
        elif value is not None:
            result[key] = _s(value)
    return result


def _decode(data: dict[str, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in data.items():
        if "S" in value:
            decoded[key] = value["S"]
        elif "N" in value:
            decoded[key] = int(value["N"])
        elif "BOOL" in value:
            decoded[key] = bool(value["BOOL"])
    return decoded


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Settings:
    bucket: str
    users_table: str
    jobs_table: str
    batch_queue: str = ""
    batch_definition: str = ""
    cpu_global_daily_limit: int = DEFAULT_CPU_GLOBAL_DAILY_LIMIT
    cpu_global_monthly_limit: int = DEFAULT_CPU_GLOBAL_MONTHLY_LIMIT
    paid_billing_enabled: bool = False
    free_lifetime_bytes: int = FREE_BYTES
    free_video_bytes: int = FREE_VIDEO_BYTES
    paid_video_bytes: int = PAID_VIDEO_BYTES
    free_report_ttl: int = FREE_REPORT_TTL_SECONDS
    paid_report_ttl: int = PAID_REPORT_TTL_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        needed = ("S3_BUCKET", "USERS_TABLE", "JOBS_TABLE")
        missing = [key for key in needed if not os.environ.get(key)]
        if missing:
            raise ApiError(503, "backend_not_configured", "AWS backend is not configured")
        return cls(
            bucket=os.environ["S3_BUCKET"],
            users_table=os.environ["USERS_TABLE"],
            jobs_table=os.environ["JOBS_TABLE"],
            batch_queue=os.getenv("CPU_BATCH_JOB_QUEUE", ""),
            batch_definition=os.getenv("CPU_BATCH_JOB_DEFINITION", ""),
            cpu_global_daily_limit=int(os.getenv("CPU_GLOBAL_DAILY_LIMIT", DEFAULT_CPU_GLOBAL_DAILY_LIMIT)),
            cpu_global_monthly_limit=int(os.getenv("CPU_GLOBAL_MONTHLY_LIMIT", DEFAULT_CPU_GLOBAL_MONTHLY_LIMIT)),
            paid_billing_enabled=os.getenv("PAID_BILLING_ENABLED", "false").lower() == "true",
            free_lifetime_bytes=int(os.getenv("FREE_LIFETIME_BYTES", FREE_BYTES)),
            free_video_bytes=int(os.getenv("FREE_MAX_VIDEO_BYTES", FREE_VIDEO_BYTES)),
            paid_video_bytes=int(os.getenv("PAID_MAX_VIDEO_BYTES", PAID_VIDEO_BYTES)),
            free_report_ttl=int(os.getenv("FREE_REPORT_TTL_SECONDS", FREE_REPORT_TTL_SECONDS)),
            paid_report_ttl=int(os.getenv("PAID_REPORT_TTL_SECONDS", PAID_REPORT_TTL_SECONDS)),
        )


class AwsBackend:
    """Small synchronous API service; AWS clients are injected for unit tests."""

    def __init__(self, settings: Settings, dynamodb: Any, s3: Any, batch: Any = None, clock: Any = time.time):
        self.cfg = settings
        self.ddb = dynamodb
        self.s3 = s3
        self.batch = batch
        self.clock = clock

    def _now(self) -> int:
        return int(self.clock())

    def _account(self, user_id: str) -> None:
        # Conditional Put makes initialization safe under concurrent first uploads.
        try:
            self.ddb.put_item(
                TableName=self.cfg.users_table,
                Item=_item({
                    "user_id": user_id,
                    "free_available_bytes": self.cfg.free_lifetime_bytes,
                    "free_reserved_bytes": 0,
                    "free_used_bytes": 0,
                    "paid_credits_available": 0,
                    "paid_credits_reserved": 0,
                    "paid_credits_used": 0,
                }),
                ConditionExpression="attribute_not_exists(user_id)",
            )
        except Exception as exc:
            if not _is_conditional(exc):
                raise

    def _record(self, job_id: str, user_id: str) -> dict[str, Any]:
        response = self.ddb.get_item(TableName=self.cfg.jobs_table, Key={"job_id": _s(job_id)}, ConsistentRead=True)
        record = _decode(response["Item"]) if "Item" in response else {}
        # Deliberately hide existence of other users' records.
        if not record or record.get("user_id") != user_id:
            raise ApiError(404, "not_found", "Video or job not found")
        return record

    def _quota_update(self, record: dict[str, Any], operation: str) -> dict[str, Any]:
        """Atomic quota delta for reserve, consume or refund of one upload."""
        tier = record["tier"]
        if tier == "free":
            amount = int(record["size_bytes"])
            available, reserved, used = "free_available_bytes", "free_reserved_bytes", "free_used_bytes"
        else:
            amount = 1  # One paid credit grants one video, independent of its byte size.
            available, reserved, used = "paid_credits_available", "paid_credits_reserved", "paid_credits_used"
        if operation == "reserve":
            return {
                "UpdateExpression": f"SET {available} = {available} - :amount, {reserved} = {reserved} + :amount",
                "ConditionExpression": f"{available} >= :amount",
                "ExpressionAttributeValues": {":amount": _n(amount)},
            }
        if operation == "consume":
            return {
                "UpdateExpression": f"SET {reserved} = {reserved} - :amount, {used} = {used} + :amount",
                "ConditionExpression": f"{reserved} >= :amount",
                "ExpressionAttributeValues": {":amount": _n(amount)},
            }
        if operation == "refund":
            return {
                "UpdateExpression": f"SET {reserved} = {reserved} - :amount, {available} = {available} + :amount",
                "ConditionExpression": f"{reserved} >= :amount",
                "ExpressionAttributeValues": {":amount": _n(amount)},
            }
        raise ValueError("Unknown quota operation")

    def _quota_transaction(self, record: dict[str, Any], operation: str, *, next_state: str = "") -> None:
        quota = self._quota_update(record, operation)
        quota.update({"TableName": self.cfg.users_table, "Key": {"user_id": _s(record["user_id"])}})
        changes: list[dict[str, Any]] = [{"Update": quota}]
        if operation == "reserve":
            changes.append({"Put": {
                "TableName": self.cfg.jobs_table,
                "Item": _item(record),
                "ConditionExpression": "attribute_not_exists(job_id)",
            }})
        else:
            expected_states = ("uploading", "uploaded") if operation == "refund" and next_state == "aborted" else ("submitted",)
            values = {":uid": _s(record["user_id"]), ":next": _s(next_state), ":updated": _s(_utc_now())}
            clauses = []
            for idx, value in enumerate(expected_states):
                key = f":state{idx}"
                values[key] = _s(value)
                clauses.append(key)
            condition = f"user_id = :uid AND #state IN ({', '.join(clauses)})"
            # Pending reservations must not have a DynamoDB TTL: automatic
            # deletion without the matching account transaction would leak
            # reserved quota indefinitely. Only terminal records expire.
            terminal_ttl = self._now() + TERMINAL_RECORD_GRACE_SECONDS
            if next_state == "succeeded":
                terminal_ttl += self._report_ttl(record)
            values[":ttl"] = _n(terminal_ttl)
            update_expr = "SET #state = :next, updated_at = :updated, ttl_epoch = :ttl"
            if next_state == "succeeded":
                values[":report_expires"] = _n(self._now() + self._report_ttl(record))
                update_expr += ", report_expires_at = :report_expires"
            changes.append({"Update": {
                "TableName": self.cfg.jobs_table,
                "Key": {"job_id": _s(record["job_id"])},
                "UpdateExpression": update_expr,
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {"#state": "status"},
                "ExpressionAttributeValues": values,
            }})
        self.ddb.transact_write_items(TransactItems=changes)

    def _report_ttl(self, record: dict[str, Any]) -> int:
        return self.cfg.free_report_ttl if record["tier"] == "free" else self.cfg.paid_report_ttl

    def _validate_start(self, body: dict[str, Any]) -> tuple[str, str, int]:
        tier = body.get("tier", "free")
        if tier not in {"free", "paid"}:
            raise ApiError(400, "invalid_request", "tier must be free or paid")
        if tier == "paid" and not self.cfg.paid_billing_enabled:
            raise ApiError(503, "billing_not_configured", "Paid analysis is not yet available")
        size_bytes = _positive_int(body.get("size_bytes"), "size_bytes")
        cap = self.cfg.free_video_bytes if tier == "free" else self.cfg.paid_video_bytes
        if size_bytes > cap:
            raise ApiError(413, "video_too_large", f"The {tier} video limit is {cap} bytes")
        content_type = body.get("content_type", "")
        if content_type not in CONTENT_TYPES:
            raise ApiError(415, "unsupported_media_type", "Only MP4, MOV and WebM video types are supported")
        return tier, content_type, size_bytes

    def _expire_stale(self, user_id: str) -> None:
        """Free abandoned multipart reservations when the owner returns.

        This complements S3's incomplete-multipart lifecycle rule. We never
        depend on DynamoDB TTL deleting reservations without a refund.
        """
        request: dict[str, Any] = {
            "TableName": self.cfg.jobs_table,
            "IndexName": "user_id-created_at-index",
            "KeyConditionExpression": "user_id = :uid",
            "FilterExpression": "#state IN (:uploading, :uploaded) AND expires_at < :now",
            "ExpressionAttributeNames": {"#state": "status"},
            "ExpressionAttributeValues": {
                ":uid": _s(user_id),
                ":uploading": _s("uploading"),
                ":uploaded": _s("uploaded"),
                ":now": _n(self._now()),
            },
        }
        while True:
            page = self.ddb.query(**request)
            for raw in page.get("Items", []):
                record = _decode(raw)
                if record.get("user_id") == user_id and record.get("status") in ("uploading", "uploaded"):
                    self._abort_record(record)
            if not page.get("LastEvaluatedKey"):
                break
            request["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def start_upload(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        tier, content_type, size_bytes = self._validate_start(body)
        self._account(user_id)
        self._expire_stale(user_id)
        video_id = uuid.uuid4().hex
        key = f"uploads/{_user_hash(user_id)}/{video_id}/original{CONTENT_TYPES[content_type]}"
        expires_at = self._now() + UPLOAD_TTL_SECONDS
        record = {
            "job_id": video_id,
            "user_id": user_id,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "uploading",
            "tier": tier,
            "size_bytes": size_bytes,
            "content_type": content_type,
            "s3_key": key,
            "expires_at": expires_at,
            "part_count": math.ceil(size_bytes / PART_BYTES),
            "report_key": f"reports/{tier}/{_user_hash(user_id)}/{video_id}/report.json",
        }
        # Reserve quota first. S3 create failures are compensated with a
        # conditional refund, preventing an orphan upload from bypassing quota.
        try:
            self._quota_transaction(record, "reserve")
        except Exception as exc:
            if _is_conditional(exc):
                code = "free_quota_exhausted" if tier == "free" else "paid_credits_exhausted"
                raise ApiError(409, code, "Insufficient remaining upload allowance") from exc
            raise
        try:
            result = self.s3.create_multipart_upload(
                Bucket=self.cfg.bucket,
                Key=key,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            upload_id = result["UploadId"]
            self.ddb.update_item(
                TableName=self.cfg.jobs_table,
                Key={"job_id": _s(video_id)},
                UpdateExpression="SET s3_upload_id = :upload_id",
                ConditionExpression="user_id = :uid AND #state = :uploading",
                ExpressionAttributeNames={"#state": "status"},
                ExpressionAttributeValues={":upload_id": _s(upload_id), ":uid": _s(user_id), ":uploading": _s("uploading")},
            )
        except Exception:
            if "upload_id" in locals():
                self._best_effort_s3_abort({**record, "s3_upload_id": upload_id})
            self._abort_record(record)
            raise
        return {
            "video_id": video_id,
            "part_size_bytes": PART_BYTES,
            "part_count": record["part_count"],
            "expires_at": expires_at,
            "tier": tier,
        }

    def _uploading(self, video_id: str, user_id: str) -> dict[str, Any]:
        record = self._record(video_id, user_id)
        if record.get("status") != "uploading":
            raise ApiError(409, "invalid_state", "Upload is no longer in progress")
        if record.get("expires_at", 0) <= self._now():
            self._abort_record(record)
            raise ApiError(410, "upload_expired", "Upload expired; start a new upload")
        if not record.get("s3_upload_id"):
            raise ApiError(409, "upload_not_ready", "Multipart upload is not ready")
        return record

    def presign_part(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        video_id = body.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ApiError(400, "invalid_request", "video_id is required")
        part = _positive_int(body.get("part_number"), "part_number")
        record = self._uploading(video_id, user_id)
        if part > record["part_count"]:
            raise ApiError(400, "invalid_request", "Part number exceeds this upload's part count")
        # Sign the exact expected Content-Length so clients cannot exceed their
        # reserved quota by uploading arbitrarily huge multipart fragments.
        # fetch(Blob) sets the Content-Length header automatically in browsers.
        part_size = min(PART_BYTES, record["size_bytes"] - (part - 1) * PART_BYTES)
        signed = self.s3.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.cfg.bucket,
                "Key": record["s3_key"],
                "UploadId": record["s3_upload_id"],
                "PartNumber": part,
                "ContentLength": part_size,
            },
            ExpiresIn=min(PRESIGN_TTL_SECONDS, record["expires_at"] - self._now()),
            HttpMethod="PUT",
        )
        return {
            "url": signed,
            "method": "PUT",
            "part_number": part,
            "required_size_bytes": part_size,
            "expires_in": min(PRESIGN_TTL_SECONDS, record["expires_at"] - self._now()),
        }

    def _validate_parts(self, body: dict[str, Any], expected: int) -> list[dict[str, Any]]:
        raw_parts = body.get("parts")
        if not isinstance(raw_parts, list) or len(raw_parts) != expected:
            raise ApiError(400, "invalid_parts", f"Expected exactly {expected} uploaded parts")
        parts = []
        for index, item in enumerate(raw_parts, start=1):
            if not isinstance(item, dict) or type(item.get("part_number")) is not int or item["part_number"] != index:
                raise ApiError(400, "invalid_parts", "Parts must be numbered consecutively from 1")
            etag = item.get("etag")
            if not isinstance(etag, str) or not ETAG_RE.fullmatch(etag):
                raise ApiError(400, "invalid_parts", "Each part requires the ETag returned by S3")
            parts.append({"ETag": etag, "PartNumber": index})
        return parts

    def complete_upload(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        video_id = body.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ApiError(400, "invalid_request", "video_id is required")
        record = self._record(video_id, user_id)
        if record.get("status") == "uploaded":
            return {"video_id": video_id, "status": "uploaded", "size_bytes": record["size_bytes"]}
        record = self._uploading(video_id, user_id)
        parts = self._validate_parts(body, record["part_count"])
        try:
            self.s3.complete_multipart_upload(
                Bucket=self.cfg.bucket,
                Key=record["s3_key"],
                UploadId=record["s3_upload_id"],
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            # Network failure after S3 success is ambiguous. Verify the final
            # object before deciding this is a failed upload.
            try:
                self.s3.head_object(Bucket=self.cfg.bucket, Key=record["s3_key"])
            except Exception:
                raise
        head = self.s3.head_object(Bucket=self.cfg.bucket, Key=record["s3_key"])
        if int(head.get("ContentLength", -1)) != record["size_bytes"]:
            self._best_effort_delete(record["s3_key"])
            self._abort_record(record)
            raise ApiError(400, "upload_size_mismatch", "Uploaded file size differs from the declared size")
        try:
            self.ddb.update_item(
                TableName=self.cfg.jobs_table,
                Key={"job_id": _s(video_id)},
                UpdateExpression="SET #state = :uploaded, updated_at = :updated",
                ConditionExpression="user_id = :uid AND #state = :uploading",
                ExpressionAttributeNames={"#state": "status"},
                ExpressionAttributeValues={":uploaded": _s("uploaded"), ":updated": _s(_utc_now()), ":uid": _s(user_id), ":uploading": _s("uploading")},
            )
        except Exception as exc:
            if not _is_conditional(exc):
                raise
            latest_state = self._record(video_id, user_id).get("status")
            if latest_state != "uploaded":
                # An abort may have won the race while S3 completed. Never
                # leave a successfully completed object after quota refund.
                if latest_state == "aborted":
                    self._best_effort_delete(record["s3_key"])
                raise ApiError(409, "upload_changed", "Upload state changed") from exc
        return {"video_id": video_id, "status": "uploaded", "size_bytes": record["size_bytes"]}

    def _best_effort_s3_abort(self, record: dict[str, Any]) -> None:
        if record.get("s3_upload_id"):
            try:
                self.s3.abort_multipart_upload(Bucket=self.cfg.bucket, Key=record["s3_key"], UploadId=record["s3_upload_id"])
            except Exception:
                pass  # S3 lifecycle still clears abandoned multipart fragments.

    def _best_effort_delete(self, key: str) -> None:
        try:
            self.s3.delete_object(Bucket=self.cfg.bucket, Key=key)
        except Exception:
            pass  # Bucket lifecycle is the last-resort cleanup.

    def _abort_record(self, record: dict[str, Any]) -> bool:
        try:
            self._quota_transaction(record, "refund", next_state="aborted")
        except Exception as exc:
            if not _is_conditional(exc):
                raise
            return False  # Another request already changed the reservation.
        if record.get("status") == "uploading":
            self._best_effort_s3_abort(record)
        elif record.get("status") == "uploaded":
            self._best_effort_delete(record["s3_key"])
        return True

    def abort_upload(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        video_id = body.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ApiError(400, "invalid_request", "video_id is required")
        record = self._record(video_id, user_id)
        if record.get("status") in ("aborted", "failed"):
            return {"video_id": video_id, "status": record["status"]}
        if record.get("status") not in ("uploading", "uploaded"):
            raise ApiError(409, "invalid_state", "An analysis already owns this upload")
        if not self._abort_record(record):
            latest = self._record(video_id, user_id)
            if latest["status"] == "aborted":
                return {"video_id": video_id, "status": "aborted"}
            raise ApiError(409, "invalid_state", "Upload has already moved to analysis")
        return {"video_id": video_id, "status": "aborted"}

    def _reserve_cpu_admission(self, record: dict[str, Any]) -> None:
        """Atomically admit exactly one Batch attempt against global UTC caps.

        Counters live in the existing users table under reserved, non-Cognito
        identifiers. Two concurrent Lambda invocations cannot both take the
        final slot: DynamoDB serializes the conditional transaction. We do
        not reset these counters after a Batch error (which may be ambiguous).
        """
        if self.cfg.cpu_global_daily_limit <= 0 or self.cfg.cpu_global_monthly_limit <= 0:
            raise ApiError(503, "compute_not_configured", "Analysis admission limits are not configured")

        utc = datetime.fromtimestamp(self._now(), timezone.utc)
        day = utc.strftime("%Y-%m-%d")
        month = utc.strftime("%Y-%m")
        counter_updates = []
        for period, limit in ((f"day/{day}", self.cfg.cpu_global_daily_limit),
                              (f"month/{month}", self.cfg.cpu_global_monthly_limit)):
            counter_updates.append({"Update": {
                "TableName": self.cfg.users_table,
                "Key": {"user_id": _s(f"__strokesense_cpu_admissions__/{period}")},
                "UpdateExpression": "SET #count = if_not_exists(#count, :zero) + :one, updated_at = :updated",
                "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
                "ExpressionAttributeNames": {"#count": "cpu_job_count"},
                "ExpressionAttributeValues": {
                    ":zero": _n(0), ":one": _n(1), ":limit": _n(limit), ":updated": _s(_utc_now()),
                },
            }})

        counter_updates.append({"Update": {
            "TableName": self.cfg.jobs_table,
            "Key": {"job_id": _s(record["job_id"])},
            "UpdateExpression": "SET #state = :next, updated_at = :updated, admission_day = :day, admission_month = :month",
            "ConditionExpression": "user_id = :uid AND #state = :state0",
            "ExpressionAttributeNames": {"#state": "status"},
            "ExpressionAttributeValues": {
                ":uid": _s(record["user_id"]), ":state0": _s("uploaded"),
                ":next": _s("submitting"), ":updated": _s(_utc_now()),
                ":day": _s(day), ":month": _s(month),
            },
        }})

        try:
            self.ddb.transact_write_items(TransactItems=counter_updates)
        except Exception as exc:
            if not _is_conditional(exc):
                raise
            latest = self._record(record["job_id"], record["user_id"])
            if latest.get("status") != "uploaded":
                raise ApiError(409, "invalid_state", "This video has already moved to analysis") from exc
            raise ApiError(429, "analysis_limit_reached", "The public beta has reached its daily or monthly analysis limit. Please try again later.") from exc

    def submit_analysis(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.cfg.batch_queue or not self.cfg.batch_definition or self.batch is None:
            raise ApiError(503, "compute_not_configured", "AWS analysis compute is not configured")
        video_id = body.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ApiError(400, "invalid_request", "video_id is required")
        record = self._record(video_id, user_id)
        if record.get("status") != "uploaded":
            raise ApiError(409, "invalid_state", "Complete this upload before starting analysis")
        # One transaction enforces the job's one-shot state transition and
        # *both* account-wide job-count limits before any paid Batch API call.
        self._reserve_cpu_admission(record)
        try:
            job = self.batch.submit_job(
                jobName=f"stroke-{video_id}",
                jobQueue=self.cfg.batch_queue,
                jobDefinition=self.cfg.batch_definition,
                containerOverrides={"environment": [
                    {"name": "STROKESENSE_JOB_ID", "value": video_id},
                    {"name": "STROKESENSE_USER_HASH", "value": _user_hash(user_id)},
                    {"name": "STROKESENSE_S3_BUCKET", "value": self.cfg.bucket},
                    {"name": "STROKESENSE_INPUT_KEY", "value": record["s3_key"]},
                    {"name": "STROKESENSE_REPORT_KEY", "value": record["report_key"]},
                ]},
            )
        except Exception as exc:
            # SubmitJob offers no idempotency token. An HTTP timeout may occur
            # AFTER AWS accepted the job; resetting to `uploaded` would allow
            # a duplicate charge. Preserve `submitting` for operator review.
            LOGGER.exception("Batch admission outcome uncertain for job %s", video_id)
            raise ApiError(503, "submission_uncertain", "Submission could not be confirmed. This video is held for review; please do not upload it again yet.") from exc
        # If this update fails after SubmitJob, a retry would not submit a
        # second job (state remains "submitting"); ops can reconcile by name.
        self.ddb.update_item(
            TableName=self.cfg.jobs_table,
            Key={"job_id": _s(video_id)},
            UpdateExpression="SET #state = :submitted, batch_job_id = :batch_id, updated_at = :updated",
            ConditionExpression="user_id = :uid AND #state = :submitting",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":submitted": _s("submitted"), ":batch_id": _s(job["jobId"]), ":updated": _s(_utc_now()), ":uid": _s(user_id), ":submitting": _s("submitting")},
        )
        return {"job_id": video_id, "video_id": video_id, "status": "submitted"}

    def _batch_status(self, record: dict[str, Any]) -> str:
        if not self.batch or not record.get("batch_job_id"):
            return "SUBMITTED"
        response = self.batch.describe_jobs(jobs=[record["batch_job_id"]])
        jobs = response.get("jobs", [])
        return str(jobs[0].get("status", "SUBMITTED")) if jobs else "SUBMITTED"

    def _report_exists(self, record: dict[str, Any]) -> bool:
        try:
            self.s3.head_object(Bucket=self.cfg.bucket, Key=record["report_key"])
        except Exception as exc:
            # A temporary S3 outage/permission error must never cause us to
            # permanently refund a job that successfully produced a report.
            if aws_error_code(exc) in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def _settle(self, record: dict[str, Any], succeeded: bool) -> None:
        state = "succeeded" if succeeded else "failed"
        operation = "consume" if succeeded else "refund"
        try:
            self._quota_transaction(record, operation, next_state=state)
        except Exception as exc:
            if not _is_conditional(exc):
                raise
            # Retries may race, but a failed transaction must not be construed
            # as success unless the record really was settled.
            fresh = self._record(record["job_id"], record["user_id"])
            if fresh.get("status") != state:
                raise ApiError(409, "job_changed", "Job state changed") from exc

    def job_status(self, user_id: str, job_id: str) -> dict[str, Any]:
        record = self._record(job_id, user_id)
        state = record["status"]
        if state == "submitted":
            batch_state = self._batch_status(record)
            if batch_state == "FAILED":
                self._settle(record, succeeded=False)
                state = "failed"
            elif batch_state == "SUCCEEDED":
                if not self._report_exists(record):
                    # A worker reporting success without an actual report is a
                    # failed analysis, not a chargeable success.
                    self._settle(record, succeeded=False)
                    state = "failed"
                else:
                    self._settle(record, succeeded=True)
                    state = "succeeded"
            elif batch_state in ("STARTING", "RUNNING", "RUNNABLE", "PENDING"):
                state = batch_state.lower()
        response: dict[str, Any] = {"job_id": job_id, "video_id": job_id, "status": state, "tier": record["tier"]}
        if state == "succeeded":
            current = self._record(job_id, user_id)
            response["report_expires_at"] = current.get("report_expires_at")
        return response

    def report_url(self, user_id: str, job_id: str) -> dict[str, Any]:
        current = self.job_status(user_id, job_id)
        if current["status"] != "succeeded":
            raise ApiError(409, "report_unavailable", "Analysis has not produced a report")
        record = self._record(job_id, user_id)
        if int(record.get("report_expires_at", 0)) <= self._now():
            raise ApiError(410, "report_expired", "This temporary report has expired")
        ttl = min(PRESIGN_TTL_SECONDS, int(record["report_expires_at"]) - self._now())
        url = self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.cfg.bucket, "Key": record["report_key"]},
            ExpiresIn=ttl,
            HttpMethod="GET",
        )
        return {"job_id": job_id, "download_url": url, "expires_in": ttl, "report_expires_at": record["report_expires_at"]}
