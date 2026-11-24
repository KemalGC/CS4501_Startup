"""Legacy membership checks for future Premium GPU analysis.

No subscription webhook or payment processor is connected. Only a verified,
trusted billing integration may later write these DynamoDB account fields.
Browser-supplied tier, email, or membership claims never grant access.
"""
from __future__ import annotations

from typing import Any
from .core import ApiError, AwsBackend, _decode, _s


def evaluate_paid_membership(record: dict[str, Any], now: int) -> None:
    """Raise a non-disclosing API error unless a current member has credits."""
    if "premium_access_granted" in record and record.get("premium_access_granted") is not True:
        raise ApiError(403, "premium_access_required",
                       "Premium access is required for GPU analysis")
    expiry = record.get("paid_membership_expires_at")
    if (record.get("paid_membership_status") != "active" or
            type(expiry) is not int or expiry <= now):
        raise ApiError(403, "paid_membership_required",
                       "An active Premium allowance is required for GPU analysis")
    credits = record.get("paid_credits_available")
    if type(credits) is not int or credits < 1:
        raise ApiError(409, "paid_credits_exhausted",
                       "No unused Premium analysis credits are available")


def require_paid_membership(service: AwsBackend, user_id: str) -> None:
    if not isinstance(user_id, str) or not user_id:
        raise ApiError(401, "unauthorized", "Sign in is required")
    # Strongly consistent; the DynamoDB credit reservation must ALSO check the
    # membership expiry in the same atomic transaction to prevent a race.
    response = service.ddb.get_item(
        TableName=service.cfg.users_table,
        Key={"user_id": _s(user_id)},
        ConsistentRead=True,
    )
    record = _decode(response["Item"]) if "Item" in response else {}
    evaluate_paid_membership(record, service._now())
