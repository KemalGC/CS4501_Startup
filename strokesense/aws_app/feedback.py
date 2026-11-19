"""Small, anonymous website-usability feedback endpoint.

The public endpoint accepts only a 1--5 rating and an optional short comment.
No identity, raw IP, browser fingerprint, or video data is saved with a review.
Atomic daily counters constrain anonymous write volume and expire via DynamoDB
TTL. Counters are best-effort anti-abuse controls, not user authentication.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .core import ApiError, _is_conditional


MAX_FEEDBACK_BODY_BYTES = 4096
MAX_COMMENT_CHARS = 1000
MAX_DAILY_SUBMISSIONS = 100
# Multiple independent users may share a campus/corporate NAT address.
MAX_PER_SOURCE_DAILY = 10
FEEDBACK_RETENTION_SECONDS = 90 * 24 * 60 * 60
COUNTER_RETENTION_SECONDS = 3 * 24 * 60 * 60


def validate_feedback(payload: dict[str, Any]) -> tuple[int, str]:
    """Reject malformed/unexpected fields rather than storing arbitrary data."""
    if not isinstance(payload, dict) or set(payload) - {"rating", "comment"}:
        raise ApiError(400, "invalid_feedback", "Provide a usability rating and optional comment only")

    rating = payload.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        raise ApiError(400, "invalid_feedback", "Usability rating must be an integer from 1 to 5")

    comment = payload.get("comment", "")
    if not isinstance(comment, str):
        raise ApiError(400, "invalid_feedback", "Comment must be text")
    comment = comment.strip()
    if len(comment) > MAX_COMMENT_CHARS:
        raise ApiError(400, "invalid_feedback", "Comment must be no more than 1000 characters")

    return rating, comment


def save_feedback(
    payload: dict[str, Any],
    *,
    dynamodb: Any,
    table_name: str,
    source_ip: str,
    now: int | None = None,
) -> dict[str, bool]:
    """Record a review if both anonymous daily limits permit it.

    The source key is a rotating per-day hash derived from API Gateway's
    requestContext.http.sourceIp, never a forwarded header supplied by a
    browser. The key is only kept for a few days, independently of the review.
    """
    if not table_name:
        raise ApiError(503, "feedback_unavailable", "Website feedback is temporarily unavailable")

    rating, comment = validate_feedback(payload)
    timestamp = int(time.time()) if now is None else int(now)
    day = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    created_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")

    # Do not persist source addresses. Missing gateway source addresses share
    # one low-volume bucket, rather than trusting spoofable X-Forwarded-For.
    source = source_ip if isinstance(source_ip, str) and source_ip else "unknown"
    source_digest = hashlib.sha256(f"{day}:{source}".encode("utf-8")).hexdigest()
    source_key = f"limit#source#{day}#{source_digest}"
    daily_key = f"limit#global#{day}"
    counter_expires = timestamp + COUNTER_RETENTION_SECONDS

    def counter_update(key: str, limit: int) -> dict[str, Any]:
        return {
            "Update": {
                "TableName": table_name,
                "Key": {"feedback_id": {"S": key}},
                "UpdateExpression": "SET #count = if_not_exists(#count, :zero) + :one, #ttl = :ttl",
                "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
                "ExpressionAttributeNames": {"#count": "submissions", "#ttl": "ttl_epoch"},
                "ExpressionAttributeValues": {
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":limit": {"N": str(limit)},
                    ":ttl": {"N": str(counter_expires)},
                },
            }
        }

    item: dict[str, dict[str, str]] = {
        "feedback_id": {"S": f"feedback#{uuid.uuid4().hex}"},
        "rating": {"N": str(rating)},
        "created_at": {"S": created_at},
        "ttl_epoch": {"N": str(timestamp + FEEDBACK_RETENTION_SECONDS)},
    }
    if comment:
        item["comment"] = {"S": comment}

    try:
        dynamodb.transact_write_items(
            TransactItems=[
                counter_update(daily_key, MAX_DAILY_SUBMISSIONS),
                counter_update(source_key, MAX_PER_SOURCE_DAILY),
                {"Put": {"TableName": table_name, "Item": item, "ConditionExpression": "attribute_not_exists(feedback_id)"}},
            ]
        )
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(429, "feedback_limit_reached", "Feedback limit reached. Please try again another day") from None
        raise

    return {"submitted": True}
