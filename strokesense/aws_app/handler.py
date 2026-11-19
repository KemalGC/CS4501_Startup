"""AWS HTTP API v2 Lambda handler for StrokeSense.

Only GET /health and POST /feedback are public. All upload, analysis, job and
report routes require a Cognito JWT verified by API Gateway; this code trusts
only claims in requestContext. Never expose a public Lambda Function URL.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

from .core import ApiError, AwsBackend, Settings
from .feedback import MAX_FEEDBACK_BODY_BYTES, save_feedback, validate_feedback


LOGGER = logging.getLogger(__name__)
MAX_JSON_BODY_BYTES = 256 * 1024
JOB_ROUTE = re.compile(r"^/analysis/jobs/([a-f0-9]{32})$")
REPORT_ROUTE = re.compile(r"^/reports/([a-f0-9]{32})$")


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(payload, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def _user_id(event: dict[str, Any]) -> str:
    auth = event.get("requestContext", {}).get("authorizer", {})
    claims = auth.get("jwt", {}).get("claims", {}) if isinstance(auth, dict) else {}
    user_id = claims.get("sub") if isinstance(claims, dict) else None
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 256:
        raise ApiError(401, "unauthorized", "Valid Cognito sign-in is required")
    return user_id


def _body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body", "")
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, str):
        raise ApiError(400, "invalid_json", "A JSON object is required")
    try:
        data = base64.b64decode(raw, validate=True) if event.get("isBase64Encoded") else raw.encode("utf-8")
        if len(data) > MAX_JSON_BODY_BYTES:
            raise ApiError(413, "request_too_large", "Request metadata is too large")
        decoded = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "invalid_json", "Request body must be valid JSON") from None
    if not isinstance(decoded, dict):
        raise ApiError(400, "invalid_json", "A JSON object is required")
    return decoded


def _build_service() -> AwsBackend:
    # Lambda execution roles supply credentials implicitly; no access keys are
    # accepted from requests or loaded from application configuration.
    import boto3

    settings = Settings.from_env()
    return AwsBackend(
        settings,
        dynamodb=boto3.client("dynamodb"),
        s3=boto3.client("s3"),
        batch=boto3.client("batch") if settings.batch_queue and settings.batch_definition else None,
    )


def _submit_public_feedback(event: dict[str, Any]) -> dict[str, bool]:
    # The only anonymous write operation. The source comes from API Gateway's
    # request context, not from untrusted forwarded headers or request JSON.
    raw = event.get("body", "")
    if isinstance(raw, str):
        max_encoded_bytes = (
            4 * ((MAX_FEEDBACK_BODY_BYTES + 2) // 3)
            if event.get("isBase64Encoded") else MAX_FEEDBACK_BODY_BYTES
        )
        if len(raw.encode("utf-8")) > max_encoded_bytes:
            raise ApiError(413, "request_too_large", "Feedback request is too large")
    table_name = os.getenv("FEEDBACK_TABLE", "")
    if not table_name:
        raise ApiError(503, "feedback_unavailable", "Website feedback is temporarily unavailable")

    payload = _body(event)
    validate_feedback(payload)
    import boto3

    http = event.get("requestContext", {}).get("http", {})
    return save_feedback(
        payload,
        dynamodb=boto3.client("dynamodb"),
        table_name=table_name,
        source_ip=str(http.get("sourceIp") or "unknown"),
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        http = event.get("requestContext", {}).get("http", {})
        method = str(http.get("method", event.get("httpMethod", ""))).upper()
        path = str(event.get("rawPath") or event.get("path") or "")

        if method == "GET" and path == "/health":
            return _response(200, {"status": "ok"})

        if method == "POST" and path == "/feedback":
            return _response(201, _submit_public_feedback(event))

        user_id = _user_id(event)
        service = _build_service()

        if method == "POST" and path == "/uploads/start":
            return _response(201, service.start_upload(user_id, _body(event)))
        if method == "POST" and path == "/uploads/part":
            return _response(200, service.presign_part(user_id, _body(event)))
        if method == "POST" and path == "/uploads/complete":
            return _response(200, service.complete_upload(user_id, _body(event)))
        if method == "POST" and path == "/uploads/abort":
            return _response(200, service.abort_upload(user_id, _body(event)))
        if method == "POST" and path == "/analysis/jobs":
            return _response(202, service.submit_analysis(user_id, _body(event)))
        match = JOB_ROUTE.fullmatch(path)
        if method == "GET" and match:
            return _response(200, service.job_status(user_id, match.group(1)))
        match = REPORT_ROUTE.fullmatch(path)
        if method == "GET" and match:
            return _response(200, service.report_url(user_id, match.group(1)))
        raise ApiError(404, "not_found", "Route not found")
    except ApiError as exc:
        return _response(exc.status, {"error": {"code": exc.code, "message": exc.message}})
    except Exception:
        LOGGER.exception("AWS backend request failed")
        return _response(503, {"error": {"code": "service_unavailable", "message": "The service is temporarily unavailable"}})
