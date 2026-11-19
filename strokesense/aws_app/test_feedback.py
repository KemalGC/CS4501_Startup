"""Offline feedback contract and abuse-limit tests (no AWS access required)."""

from __future__ import annotations

import copy
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

from aws_app.core import ApiError
from aws_app.feedback import (
    COUNTER_RETENTION_SECONDS,
    FEEDBACK_RETENTION_SECONDS,
    MAX_DAILY_SUBMISSIONS,
    MAX_PER_SOURCE_DAILY,
    save_feedback,
    validate_feedback,
)
from aws_app.handler import lambda_handler


class ConditionalFailure(Exception):
    response = {
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
    }


class MemoryFeedbackDynamo:
    def __init__(self):
        self.records: dict[str, dict] = {}

    def transact_write_items(self, *, TransactItems):
        records = copy.deepcopy(self.records)
        for action in TransactItems:
            if "Update" in action:
                update = action["Update"]
                key = update["Key"]["feedback_id"]["S"]
                values = update["ExpressionAttributeValues"]
                limit = int(values[":limit"]["N"])
                count = records.get(key, {}).get("submissions", 0)
                if count >= limit:
                    raise ConditionalFailure
                records[key] = {
                    "feedback_id": key,
                    "submissions": count + 1,
                    "ttl_epoch": int(values[":ttl"]["N"]),
                }
            else:
                put = action["Put"]
                item = put["Item"]
                key = item["feedback_id"]["S"]
                if key in records:
                    raise ConditionalFailure
                records[key] = {
                    name: int(value["N"]) if "N" in value else value["S"]
                    for name, value in item.items()
                }
        self.records = records

    def reviews(self):
        return [item for key, item in self.records.items() if key.startswith("feedback#")]


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.ddb = MemoryFeedbackDynamo()
        self.now = 1_800_000_000

    def submit(self, rating=5, comment="Really useful", source="192.0.2.1", now=None):
        return save_feedback(
            {"rating": rating, "comment": comment},
            dynamodb=self.ddb,
            table_name="feedback",
            source_ip=source,
            now=self.now if now is None else now,
        )

    def test_rating_and_optional_comment_strictly_validated(self):
        self.assertEqual(validate_feedback({"rating": 1}), (1, ""))
        self.assertEqual(validate_feedback({"rating": 5, "comment": "  Works  "}), (5, "Works"))
        invalid = [
            {}, {"rating": 0}, {"rating": 6}, {"rating": "3"},
            {"rating": 3.5}, {"rating": True}, {"rating": 2, "comment": None},
            {"rating": 3, "comment": "a" * 1001},
            {"rating": 3, "email": "private@example.com"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ApiError) as context:
                validate_feedback(payload)
            self.assertEqual(context.exception.status, 400)

    def test_saves_no_user_identity_ip_or_video_and_expires_in_90_days(self):
        self.assertEqual(self.submit(), {"submitted": True})
        review = self.ddb.reviews()[0]
        self.assertEqual(review["rating"], 5)
        self.assertEqual(review["comment"], "Really useful")
        self.assertEqual(review["ttl_epoch"], self.now + FEEDBACK_RETENTION_SECONDS)
        self.assertEqual(review["created_at"], "2027-01-15T08:00:00+00:00")
        self.assertNotIn("192.0.2.1", json.dumps(self.ddb.records))
        for private_field in ("user_id", "email", "ip_address", "video_id", "job_id"):
            self.assertNotIn(private_field, review)
        counters = [r for k, r in self.ddb.records.items() if k.startswith("limit#")]
        self.assertEqual(len(counters), 2)
        self.assertTrue(all(r["ttl_epoch"] == self.now + COUNTER_RETENTION_SECONDS for r in counters))

    def test_source_daily_cap_and_reset_at_new_utc_day(self):
        for _ in range(MAX_PER_SOURCE_DAILY):
            self.submit()
        with self.assertRaises(ApiError) as blocked:
            self.submit()
        self.assertEqual(blocked.exception.status, 429)
        self.assertEqual(blocked.exception.code, "feedback_limit_reached")
        self.assertEqual(len(self.ddb.reviews()), MAX_PER_SOURCE_DAILY)
        self.assertEqual(self.submit(now=self.now + 86400), {"submitted": True})
        self.assertEqual(len(self.ddb.reviews()), MAX_PER_SOURCE_DAILY + 1)

    def test_global_daily_limit_enforced_atomically(self):
        for i in range(MAX_DAILY_SUBMISSIONS):
            self.submit(source=f"2001:db8::{i}")
        with self.assertRaises(ApiError) as blocked:
            self.submit(source="2001:db8::next")
        self.assertEqual(blocked.exception.status, 429)
        self.assertEqual(len(self.ddb.reviews()), MAX_DAILY_SUBMISSIONS)
        # A rejected write must not increment the source quota counter.
        self.assertNotIn("2001:db8::next", json.dumps(self.ddb.records))

    def test_unconfigured_feedback_fails_closed(self):
        with self.assertRaises(ApiError) as unconfigured:
            save_feedback({"rating": 4}, dynamodb=self.ddb, table_name="", source_ip="192.0.2.1")
        self.assertEqual(unconfigured.exception.status, 503)
        self.assertEqual(self.ddb.records, {})

    def test_anonymous_http_route_works_and_video_routes_remain_protected(self):
        fake_boto3 = types.SimpleNamespace(client=lambda service: self.ddb)
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "192.0.2.5"}},
            "rawPath": "/feedback",
            "body": json.dumps({"rating": 4, "comment": "Neat!"}),
        }
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.dict(os.environ, {"FEEDBACK_TABLE": "feedback"}):
            response = lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 201)
            self.assertEqual(json.loads(response["body"]), {"submitted": True})
            oversized = {**event, "body": " " * 4100}
            self.assertEqual(lambda_handler(oversized, None)["statusCode"], 413)
            unauthenticated_upload = {**event, "rawPath": "/uploads/start"}
            self.assertEqual(lambda_handler(unauthenticated_upload, None)["statusCode"], 401)


if __name__ == "__main__":
    unittest.main()
