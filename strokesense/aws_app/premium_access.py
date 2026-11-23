"""Admin-managed Premium entitlements, separate from GPU runtime readiness.

Cognito supplies identity; the account table supplies access. An operator pins
the owner's immutable Cognito subject after verifying their email. Neither an
email supplied by the browser nor an administrator grant creates admin rights,
credits, billing, GPU capacity, or a submission path.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import unicodedata
import uuid
from typing import Any

from .core import ApiError, AwsBackend, _decode, _is_conditional, _item, _s, aws_error_code
from .library import require_admin


_SUBJECT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EMAIL = re.compile(r'^[^@\s"\\<>]+@[^@\s"\\<>]+\.[^@\s"\\<>]+$')
_NOT_FOUND = "No enabled account with a verified email was found. The user must sign in first."


def _subject(value: Any) -> str:
    if not isinstance(value, str) or not _SUBJECT.fullmatch(value):
        raise ApiError(400, "invalid_premium_user", "A valid Cognito account ID is required")
    return value


def _email(value: Any) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_email", "Enter the account's exact email address")
    email = value.strip()
    if len(email) > 254 or not _EMAIL.fullmatch(email) or any(unicodedata.category(c).startswith("C") for c in email):
        raise ApiError(400, "invalid_email", "Enter the account's exact email address")
    return email


def _identity_client(service: AwsBackend) -> Any:
    if (not service.cfg.cognito_user_pool_id or service.cognito is None
            or (service.cfg.premium_owner_sub and not _SUBJECT.fullmatch(service.cfg.premium_owner_sub))):
        raise ApiError(503, "premium_not_configured", "Premium access management is not configured")
    return service.cognito


def _read_identity(service: AwsBackend, username: str, *, expected_sub: str = "", expected_email: str = "") -> dict[str, Any]:
    client = _identity_client(service)
    if not isinstance(username, str) or not username or len(username) > 128:
        raise ApiError(404, "premium_user_not_found", _NOT_FOUND)
    try:
        user = client.admin_get_user(UserPoolId=service.cfg.cognito_user_pool_id, Username=username)
    except Exception as exc:
        if aws_error_code(exc) == "UserNotFoundException":
            raise ApiError(404, "premium_user_not_found", _NOT_FOUND) from exc
        raise ApiError(503, "premium_identity_unavailable", "Account identity could not be verified") from exc
    attributes = {a.get("Name"): a.get("Value") for a in user.get("UserAttributes", []) if isinstance(a, dict)}
    subject, email = attributes.get("sub"), attributes.get("email")
    if (user.get("Enabled") is not True or user.get("UserStatus") not in {"CONFIRMED", "EXTERNAL_PROVIDER"}
            or not isinstance(subject, str) or not _SUBJECT.fullmatch(subject)
            or not isinstance(email, str) or len(email) > 254 or not _EMAIL.fullmatch(email)
            or any(unicodedata.category(c).startswith("C") for c in email)
            or attributes.get("email_verified") != "true"
            or (expected_sub and subject != expected_sub)
            or (expected_email and email.casefold() != expected_email.casefold())):
        raise ApiError(404, "premium_user_not_found", _NOT_FOUND)
    return {"user_id": subject, "email": email, "email_verified": True}


def _find_identity(service: AwsBackend, attribute: str, value: str) -> dict[str, Any] | None:
    """Exhaust exact-match search before selecting an identity; then re-read it.

    ListUsers is eventually consistent and is only a way to discover the IdP
    username. AdminGetUser validates the current enabled/verified identity.
    """
    client = _identity_client(service)
    request: dict[str, Any] = {
        "UserPoolId": service.cfg.cognito_user_pool_id,
        "Filter": f"{attribute} = {json.dumps(value)}",
        "Limit": 60,
    }
    usernames: set[str] = set()
    tokens: set[str] = set()
    for _ in range(10):
        try:
            page = client.list_users(**request)
        except Exception as exc:
            raise ApiError(503, "premium_identity_unavailable", "Account identity could not be verified") from exc
        for user in page.get("Users", []):
            username = user.get("Username") if isinstance(user, dict) else None
            if not isinstance(username, str) or not username:
                raise ApiError(503, "premium_identity_unavailable", "Account identity could not be verified")
            usernames.add(username)
        if len(usernames) > 1:
            raise ApiError(409, "premium_identity_ambiguous", "More than one account matches. Resolve the duplicate Cognito identities before changing access.")
        token = page.get("PaginationToken")
        if not token:
            if not usernames:
                return None
            return _read_identity(
                service, next(iter(usernames)),
                expected_sub=value if attribute == "sub" else "",
                expected_email=value if attribute == "email" else "",
            )
        if not isinstance(token, str) or token in tokens:
            break
        tokens.add(token)
        request["PaginationToken"] = token
    raise ApiError(503, "premium_identity_unavailable", "Account search could not be completed safely")


def _account_record(service: AwsBackend, user_id: str) -> dict[str, Any]:
    response = service.ddb.get_item(
        TableName=service.cfg.users_table, Key={"user_id": _s(user_id)}, ConsistentRead=True,
    )
    return _decode(response["Item"]) if "Item" in response else {}


def access_view(service: AwsBackend, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
    granted = record.get("premium_access_granted") is True
    # The current production API deliberately refuses GPU submissions. A smoke
    # success, entitlement, or feature flag alone must never report readiness.
    return {
        "granted": granted,
        "available": False,
        "reason": "gpu_not_ready" if granted else "access_required",
        "source": record.get("premium_access_source") if record.get("premium_access_source") in {"owner", "admin"} else None,
        "updated_at": record.get("premium_access_updated_at"),
        "owner_protected": user_id == service.cfg.premium_owner_sub,
    }


def _user_view(service: AwsBackend, identity: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return {**identity, "premium_access": access_view(service, identity["user_id"], record)}


def _write_access(
    service: AwsBackend, user_id: str, actor_sub: str, enabled: bool, reason: str,
    before: dict[str, Any], *, bootstrap: bool = False,
) -> dict[str, Any]:
    if not service.cfg.admin_audit_table:
        raise ApiError(503, "audit_unavailable", "Premium access changes cannot be recorded")
    now = service._now()
    updated_at = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
    source = "owner" if user_id == service.cfg.premium_owner_sub else "admin"
    fields = {
        "premium_access_granted": enabled,
        "premium_access_source": source,
        "premium_access_updated_at": updated_at,
        "premium_access_updated_by": actor_sub,
        "premium_access_reason": reason,
        "premium_access_version": uuid.uuid4().hex,
    }
    values = {f":v{index}": value for index, value in enumerate(_item(fields).values())}
    assignments = [f"{name} = :v{index}" for index, name in enumerate(fields)]
    condition = "user_id = :subject"
    values[":subject"] = _s(user_id)
    if bootstrap:
        condition += " AND attribute_not_exists(premium_access_granted)"
    elif "premium_access_version" in before:
        condition += " AND premium_access_version = :previous_version"
        values[":previous_version"] = _s(before["premium_access_version"])
    else:
        condition += " AND attribute_not_exists(premium_access_version)"
        if "premium_access_granted" in before:
            condition += " AND premium_access_granted = :previous_granted"
            values[":previous_granted"] = _item({"value": before["premium_access_granted"]})["value"]
        else:
            condition += " AND attribute_not_exists(premium_access_granted)"
    audit = {
        "audit_id": uuid.uuid4().hex,
        "action": "premium_owner_bootstrapped" if bootstrap else "premium_access_granted" if enabled else "premium_access_revoked",
        "actor_sub": actor_sub,
        "target_sub": user_id,
        "granted": enabled,
        "source": source,
        "reason": reason,
        "issued_at": updated_at,
        "access_version": fields["premium_access_version"],
        "ttl_epoch": now + min(365, max(30, int(os.getenv("ADMIN_AUDIT_TTL_DAYS", "90")))) * 86400,
    }
    try:
        service.ddb.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": service.cfg.users_table,
                "Key": {"user_id": _s(user_id)},
                "UpdateExpression": "SET " + ", ".join(assignments),
                "ConditionExpression": condition,
                "ExpressionAttributeValues": values,
            }},
            {"Put": {
                "TableName": service.cfg.admin_audit_table,
                "Item": _item(audit),
                "ConditionExpression": "attribute_not_exists(audit_id)",
            }},
        ])
    except Exception as exc:
        if _is_conditional(exc):
            raise ApiError(409, "premium_access_conflict", "Access changed in another request. Refresh the account and try again.") from exc
        raise ApiError(503, "audit_unavailable", "The access change could not be confirmed. Refresh the account before retrying.") from exc
    return {**before, **fields}


def _current_identity(service: AwsBackend, claims: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(claims, dict) or claims.get("token_use") != "access":
        raise ApiError(401, "unauthorized", "A Cognito access token is required")
    user_id = claims.get("sub")
    username = claims.get("username")
    if not isinstance(user_id, str) or not _SUBJECT.fullmatch(user_id) or not isinstance(username, str) or not username:
        raise ApiError(401, "unauthorized", "Valid Cognito sign-in is required")
    try:
        return _read_identity(service, username, expected_sub=user_id)
    except ApiError as exc:
        if exc.code == "premium_user_not_found":
            raise ApiError(403, "premium_identity_unverified", "An enabled account with a verified email is required for Premium access") from exc
        raise


def _require_current_admin(service: AwsBackend, claims: dict[str, Any]) -> str:
    admin_sub = require_admin(claims)
    # API Gateway validates JWT signatures, but an already-issued token can
    # outlive a disabled account. Recheck the actor before privileged reads or
    # writes, not only when the browser fetches /me.
    _current_identity(service, claims)
    return admin_sub


def account_access(service: AwsBackend, claims: dict[str, Any]) -> dict[str, Any]:
    identity = _current_identity(service, claims)
    user_id = identity["user_id"]
    record = _account_record(service, user_id)
    if user_id == service.cfg.premium_owner_sub and "premium_access_granted" not in record:
        service._account(user_id)
        try:
            record = _write_access(
                service, user_id, user_id, True,
                "Initial access for the operator-verified owner account",
                record, bootstrap=True,
            )
        except ApiError as exc:
            if exc.code != "premium_access_conflict":
                raise
            record = _account_record(service, user_id)
            if "premium_access_granted" not in record:
                raise
    try:
        require_admin(claims)
        is_admin = True
    except ApiError:
        is_admin = False
    return {"user_id": identity["user_id"], "is_admin": is_admin, "premium_access": access_view(service, user_id, record)}


def lookup_premium_user(service: AwsBackend, claims: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    _require_current_admin(service, claims)
    identity = _find_identity(service, "email", _email(query.get("email")))
    if identity is None:
        return {"users": []}
    return {"users": [_user_view(service, identity, _account_record(service, identity["user_id"]))]}


def change_premium_access(
    service: AwsBackend, claims: dict[str, Any], user_id: str, body: dict[str, Any],
) -> dict[str, Any]:
    actor_sub = _require_current_admin(service, claims)
    user_id = _subject(user_id)
    enabled, reason = body.get("enabled"), body.get("reason")
    if (set(body) - {"enabled", "reason"} or type(enabled) is not bool
            or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500
            or any(unicodedata.category(c).startswith("C") for c in reason)):
        raise ApiError(400, "invalid_premium_access", "Choose grant or revoke and provide a reason of 3 to 500 visible characters")
    if user_id == service.cfg.premium_owner_sub and not enabled:
        raise ApiError(403, "premium_owner_protected", "The configured owner's Premium access is managed by the deployment operator")
    identity = _find_identity(service, "sub", user_id)
    if identity is None:
        raise ApiError(404, "premium_user_not_found", _NOT_FOUND)
    service._account(user_id)
    record = _write_access(service, user_id, actor_sub, enabled, reason.strip(), _account_record(service, user_id))
    return _user_view(service, identity, record)


def require_premium_access(service: AwsBackend, user_id: str) -> None:
    """Strong entitlement read for the future dispatcher integration.

    Callers must still enforce runtime readiness and atomically recheck access
    when admitting work. This function does not enable or enqueue GPU work.
    """
    if _account_record(service, _subject(user_id)).get("premium_access_granted") is not True:
        raise ApiError(403, "premium_access_required", "Premium access is required for GPU analysis")
