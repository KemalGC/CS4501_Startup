"""Privacy regression tests for explicit public community sharing (no AWS credentials)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from aws_app.community import (
    change_community_visibility, community_video_url, list_community_videos,
)
from aws_app.core import ApiError, AwsBackend, Settings, _item, _user_hash
from aws_app.handler import lambda_handler
from aws_app.test_backend import FakeAwsError, FakeS3


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.owner = "owner-user-123"
        self.job_id = "a" * 32
        self.other_id = "b" * 32
        self.record = self._record(self.job_id, self.owner)
        self.other = self._record(self.other_id, "other-owner")
        self.ddb = MagicMock()
        self.ddb.get_item.side_effect = self._get_item
        self.s3 = FakeS3()
        self.s3.objects[self._annotated_key(self.record)] = 25_000
        self.s3.objects[self._annotated_key(self.other)] = 25_000
        self.svc = AwsBackend(Settings("media", "users", "jobs"), self.ddb, self.s3, clock=lambda: self.now)

    def _record(self, job_id, owner):
        return {
            "job_id": job_id, "user_id": owner, "tier": "free",
            "status": "succeeded", "created_at": "2026-11-19T12:00:00+00:00",
            "filename": "private-training-video.mp4",
            "report_key": f"reports/free/{_user_hash(owner)}/{job_id}/report.json",
            "report_expires_at": self.now + 86400,
            "community_shared": False, "allow_admin_review": False,
            "video_duration_ms": 12800,
        }

    def _annotated_key(self, record):
        return record["report_key"][:-len("report.json")] + "annotated.mp4"

    def _get_item(self, **kwargs):
        job_id = kwargs["Key"]["job_id"]["S"]
        record = {self.job_id: self.record, self.other_id: self.other}.get(job_id)
        return {"Item": _item(record)} if record else {}

    def _public(self, record):
        record.update({
            "community_shared": True, "community_partition": "PUBLIC",
            "community_published_at": "2026-11-19T12:30:00+00:00",
        })

    def test_private_and_admin_only_are_never_public(self):
        self.record["allow_admin_review"] = True
        self.record["admin_partition"] = "OPTED_IN"
        self.ddb.query.return_value = {"Items": [_item(self.record)]}
        self.assertEqual(list_community_videos(self.svc, {})["videos"], [])
        with self.assertRaises(ApiError) as exc:
            community_video_url(self.svc, self.job_id)
        self.assertEqual(exc.exception.status, 404)
        self.s3.generate_presigned_url = MagicMock()
        self.s3.generate_presigned_url.assert_not_called()

    def test_owner_only_opt_in_checks_annotated_media_and_state(self):
        with self.assertRaises(ApiError) as exc:
            change_community_visibility(self.svc, "not-the-owner", self.job_id, {"public": True})
        self.assertEqual(exc.exception.status, 404)
        with self.assertRaises(ApiError):
            change_community_visibility(self.svc, self.owner, self.job_id, {"public": "true"})
        self.s3.objects.pop(self._annotated_key(self.record))
        with self.assertRaises(ApiError) as exc:
            change_community_visibility(self.svc, self.owner, self.job_id, {"public": True})
        self.assertEqual(exc.exception.status, 409)
        self.s3.objects[self._annotated_key(self.record)] = 25_000
        outcome = change_community_visibility(self.svc, self.owner, self.job_id, {"public": True})
        self.assertTrue(outcome["public"])
        params = self.ddb.update_item.call_args.kwargs
        self.assertIn("report_expires_at > :now", params["ConditionExpression"])
        self.assertIn("user_id = :uid", params["ConditionExpression"])
        self.assertEqual(params["ExpressionAttributeValues"][":partition"], {"S": "PUBLIC"})
        self.assertEqual(params["ExpressionAttributeValues"][":report"], {"S": self.record["report_key"]})
        self.assertFalse(self.ddb.transact_write_items.called, "publishing must not consume another paid compute slot")

    def test_expired_or_failed_cannot_publish(self):
        self.record["report_expires_at"] = self.now - 1
        with self.assertRaises(ApiError):
            change_community_visibility(self.svc, self.owner, self.job_id, {"public": True})
        self.record["report_expires_at"] = self.now + 100
        self.record["status"] = "failed"
        with self.assertRaises(ApiError):
            change_community_visibility(self.svc, self.owner, self.job_id, {"public": True})
        self.ddb.update_item.assert_not_called()

    def test_public_listing_contains_no_private_metadata_and_checks_stale_index(self):
        self._public(self.record)
        self.ddb.query.return_value = {"Items": [_item(self.record), _item(self.other)]}
        result = list_community_videos(self.svc, {"limit": "12"})
        self.assertEqual(len(result["videos"]), 1)
        card = result["videos"][0]
        self.assertEqual(card["job_id"], self.job_id)
        self.assertEqual(card["duration_seconds"], 12.8)
        for forbidden in ("user_id", "owner", "filename", "report_key", "s3_key", "email",
                          "allow_admin_review", "original_video_url", "video_url"):
            self.assertNotIn(forbidden, card)
        call = self.ddb.query.call_args.kwargs
        self.assertEqual(call["IndexName"], "community_partition-created_at-index")
        self.assertTrue(call["KeyConditionExpression"].startswith("community_partition"))
        self.assertTrue(self.ddb.get_item.call_args.kwargs["ConsistentRead"])
        # A recently unpublished record may still be in the eventually consistent GSI.
        self.record.pop("community_partition")
        self.record["community_shared"] = False
        self.assertEqual(list_community_videos(self.svc, {})["videos"], [])

    def test_public_playback_signs_only_annotated_mp4_and_conditional_permission(self):
        self._public(self.record)
        result = community_video_url(self.svc, self.job_id)
        self.assertEqual(result["video_type"], "annotated")
        self.assertEqual(result["expires_in"], 60)
        self.assertEqual(self.s3.presigned_params["Key"], self._annotated_key(self.record))
        self.assertNotIn("original", self.s3.presigned_params["Key"])
        check = self.ddb.transact_write_items.call_args.kwargs["TransactItems"][0]["ConditionCheck"]
        self.assertIn("community_shared = :yes", check["ConditionExpression"])
        self.assertIn("report_expires_at > :now", check["ConditionExpression"])
        self.assertIn("report_key = :report", check["ConditionExpression"])
        self.ddb.transact_write_items.side_effect = FakeAwsError(
            "TransactionCanceledException", [{"Code": "ConditionalCheckFailed"}]
        )
        with self.assertRaises(ApiError) as exc:
            community_video_url(self.svc, self.job_id)
        self.assertEqual(exc.exception.status, 404)

    def test_unpublish_removes_sparse_index_and_old_link_is_bounded(self):
        self._public(self.record)
        result = change_community_visibility(self.svc, self.owner, self.job_id, {"public": False})
        self.assertFalse(result["public"])
        call = self.ddb.update_item.call_args.kwargs
        self.assertIn("REMOVE community_partition", call["UpdateExpression"])
        self.assertNotIn(":partition", call["ExpressionAttributeValues"])
        self.record["community_shared"] = False
        self.record.pop("community_partition")
        with self.assertRaises(ApiError):
            community_video_url(self.svc, self.job_id)
        self.assertEqual(self.s3.presigned_calls, [])

    def test_anonymous_list_but_owner_only_publication_route(self):
        listing = {
            "rawPath": "/community/videos", "requestContext": {"http": {"method": "GET"}}
        }
        publish = {
            "rawPath": f"/analysis/jobs/{self.job_id}/publish",
            "requestContext": {"http": {"method": "POST"}},
            "body": '{"public":true}',
        }
        with patch("aws_app.handler._build_service", return_value=self.svc):
            result = lambda_handler(listing, None)
            self.assertEqual(result["statusCode"], 200)
            self.assertEqual(lambda_handler(publish, None)["statusCode"], 401)
            publish["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": self.owner}}}
            self.assertEqual(lambda_handler(publish, None)["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
