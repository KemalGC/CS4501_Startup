"""Offline tests for permanent owner-only deletion and 15-minute cleanup retry."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from aws_app.core import ApiError, AwsBackend, Settings, _item, _user_hash
from aws_app.deletion import delete_owned_analysis
from aws_app.handler import lambda_handler
from aws_app.library import list_owner_jobs
from aws_app.reconcile import reconcile_due


class StorageError(Exception):
    pass


class FakeDynamo:
    def __init__(self):
        self.jobs = {}
        self.users = {"owner": {"free_used_bytes": 24000000}}
        self.updates = []
        self.deleted = []
        self.index_snapshot = []

    def get_item(self, **kwargs):
        record = self.jobs.get(kwargs["Key"]["job_id"]["S"])
        return {"Item": _item(record)} if record else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        id_ = kwargs["Key"]["job_id"]["S"]
        rec = self.jobs.get(id_)
        values = kwargs["ExpressionAttributeValues"]
        if (not rec or rec.get("user_id") != values[":uid"]["S"]
                or rec.get("status") not in ("succeeded", "failed", "aborted")):
            raise StorageError("unexpected conditional update")
        rec.update({
            "status": "deleting",
            "updated_at": values[":updated"]["S"],
            "ttl_epoch": int(values[":ttl"]["N"]),
            "expires_at": int(values[":due"]["N"]),
            "allow_admin_review": False,
            "community_shared": False,
        })
        rec.pop("admin_partition", None)
        rec.pop("community_partition", None)

    def delete_item(self, **kwargs):
        id_ = kwargs["Key"]["job_id"]["S"]
        record = self.jobs.get(id_)
        if not record or record.get("status") != "deleting":
            raise StorageError("unexpected deletion state")
        self.deleted.append(kwargs)
        del self.jobs[id_]

    def query(self, **kwargs):
        index = kwargs["IndexName"]
        if index == "user_id-created_at-index":
            rows = [j for j in self.index_snapshot
                    if j.get("user_id") == kwargs["ExpressionAttributeValues"][":partition"]["S"]]
        elif index == "status-expires_at-index":
            values = kwargs["ExpressionAttributeValues"]
            rows = [j for j in self.jobs.values() if
                    j["status"] == values[":state"]["S"] and j.get("expires_at", 0) < int(values[":now"]["N"])]
        else:
            rows = []
        return {"Items": [_item(j) for j in rows]}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.deletion_calls = 0
        self.fail_list_once = False

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs["Key"])
        self.objects.pop(kwargs["Key"], None)

    def list_objects_v2(self, **kwargs):
        if self.fail_list_once:
            self.fail_list_once = False
            raise StorageError("simulated S3 outage")
        prefix = kwargs["Prefix"]
        names = [key for key in self.objects if key.startswith(prefix)]
        return {"Contents": [{"Key": key} for key in names[:kwargs["MaxKeys"]]], "IsTruncated": len(names) > kwargs["MaxKeys"]}

    def delete_objects(self, **kwargs):
        self.deletion_calls += 1
        for obj in kwargs["Delete"]["Objects"]:
            self.deleted.append(obj["Key"])
            self.objects.pop(obj["Key"], None)
        return {"Errors": []}


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.user_id = "owner"
        self.other_id = "stranger"
        self.job = "c" * 32
        self.ddb = FakeDynamo()
        self.s3 = FakeS3()
        self.settings = Settings(bucket="media", users_table="users", jobs_table="jobs")
        self.svc = AwsBackend(self.settings, self.ddb, self.s3, clock=lambda: self.now)
        self.original = f"uploads/{_user_hash('owner')}/{self.job}/original.mp4"
        self.report_prefix = f"reports/free/{_user_hash('owner')}/{self.job}/"
        self.record = {
            "job_id": self.job, "user_id": "owner", "status": "succeeded",
            "tier": "free", "content_type": "video/mp4", "s3_key": self.original,
            "report_key": self.report_prefix + "report.json",
            "size_bytes": 24_000_000, "created_at": "2026-11-19T12:00:00+00:00",
            "expires_at": self.now - 20, "report_expires_at": self.now + 3600,
            "filename": "secret-rowing-session.mp4", "allow_admin_review": True,
            "admin_partition": "OPTED_IN", "community_shared": True,
            "community_partition": "PUBLIC",
        }
        self.ddb.jobs[self.job] = self.record
        self.ddb.index_snapshot = [copy.deepcopy(self.record)]
        for key in [self.original, self.report_prefix + "report.json",
                    self.report_prefix + "annotated.mp4",
                    self.report_prefix + "artifacts.json",
                    self.report_prefix + "runtime-metrics.json",
                    self.report_prefix + "frames/rower-1.jpg"]:
            self.s3.objects[key] = 100
        self.s3.objects["reports/free/different-user/not-my-job/report.json"] = 200

    def test_owner_delete_removes_report_video_frames_and_index_record(self):
        before = copy.deepcopy(self.ddb.users)
        outcome = delete_owned_analysis(self.svc, self.user_id, self.job)
        self.assertEqual(outcome, {"job_id": self.job, "status": "deleted"})
        self.assertNotIn(self.job, self.ddb.jobs)
        self.assertIn(self.original, self.s3.deleted)
        self.assertIn(self.report_prefix + "annotated.mp4", self.s3.deleted)
        self.assertIn(self.report_prefix + "frames/rower-1.jpg", self.s3.deleted)
        self.assertEqual(self.ddb.users, before, "deletion must never refund a successful job")
        self.assertEqual(len(self.ddb.deleted), 1)
        self.assertEqual(len(self.s3.objects), 1)
        self.assertIn("reports/free/different-user/not-my-job/report.json", self.s3.objects)
        self.assertEqual(list_owner_jobs(self.svc, self.user_id, {})["jobs"], [],
                         "a stale eventually consistent owner index cannot resurrect a deleted job")

    def test_stranger_and_running_job_cannot_delete(self):
        with self.assertRaises(ApiError) as unauthorized:
            delete_owned_analysis(self.svc, self.other_id, self.job)
        self.assertEqual(unauthorized.exception.status, 404)
        for status in ("uploading", "uploaded", "submitted", "submitting"):
            self.record["status"] = status
            with self.subTest(status=status), self.assertRaises(ApiError) as err:
                delete_owned_analysis(self.svc, self.user_id, self.job)
            self.assertEqual(err.exception.status, 409)
        self.assertEqual(self.s3.deleted, [])
        self.assertEqual(self.ddb.updates, [])

    def test_corrupted_s3_paths_are_rejected_without_touching_any_object(self):
        self.record["report_key"] = f"reports/free/{_user_hash('stranger')}/{self.job}/report.json"
        with self.assertRaises(ApiError) as err:
            delete_owned_analysis(self.svc, self.user_id, self.job)
        self.assertEqual(err.exception.status, 409)
        self.assertEqual(self.s3.deleted, [])
        self.assertEqual(self.ddb.updates, [])

    def test_partial_outage_queues_cleanup_and_reconciler_finishes(self):
        self.s3.fail_list_once = True
        outcome = delete_owned_analysis(self.svc, self.user_id, self.job)
        self.assertEqual(outcome["status"], "deleting")
        self.assertEqual(self.record["status"], "deleting")
        self.assertFalse(self.record["allow_admin_review"])
        self.assertFalse(self.record["community_shared"])
        self.assertNotIn("admin_partition", self.record)
        self.assertNotIn("community_partition", self.record)
        self.assertEqual(list_owner_jobs(self.svc, self.user_id, {})["jobs"], [])
        with self.assertRaises(ApiError) as err:
            self.svc.report_artifacts(self.user_id, self.job)
        self.assertEqual(err.exception.status, 404)
        before = copy.deepcopy(self.ddb.users)
        stats = reconcile_due(self.svc)
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["errors"], 0)
        self.assertNotIn(self.job, self.ddb.jobs)
        self.assertEqual(self.ddb.users, before)

    def test_api_is_authenticated_and_does_not_trust_submitted_account_ids(self):
        unauth = {"rawPath": f"/analysis/jobs/{self.job}/delete",
                  "requestContext": {"http": {"method": "POST"}}}
        with patch("aws_app.handler._build_service", return_value=self.svc):
            self.assertEqual(lambda_handler(unauth, None)["statusCode"], 401)
            owner = {**unauth, "requestContext": {
                "http": {"method": "POST"},
                "authorizer": {"jwt": {"claims": {"sub": self.user_id}}},
            }}
            answer = lambda_handler(owner, None)
        self.assertEqual(answer["statusCode"], 200)
        self.assertNotIn(self.job, self.ddb.jobs)

    def test_failed_analysis_can_delete_without_changing_refund(self):
        self.record["status"] = "failed"
        self.record["allow_admin_review"] = False
        before = copy.deepcopy(self.ddb.users)
        self.assertEqual(delete_owned_analysis(self.svc, self.user_id, self.job)["status"], "deleted")
        self.assertEqual(self.ddb.users, before)


if __name__ == "__main__":
    unittest.main()
