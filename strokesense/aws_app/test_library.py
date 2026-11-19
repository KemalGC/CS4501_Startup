"""No-network tests for private history, timing, consent, admin RBAC/audit."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from aws_app.core import ApiError, AwsBackend, Settings, _item
from aws_app.handler import lambda_handler
from aws_app.library import (
    admin_video_url,
    batch_timings,
    change_review_consent,
    list_owner_jobs,
    list_review_jobs,
    require_admin,
)
from aws_app.test_backend import FakeBatch, FakeS3, MemoryDynamo


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.ddb = MemoryDynamo()
        self.s3 = FakeS3()
        self.batch = FakeBatch()
        self.cfg = Settings("media", "users", "jobs", "batch-queue", "batch-def", admin_audit_table="audit", raw_upload_ttl_seconds=86400)
        self.backend = AwsBackend(self.cfg, self.ddb, self.s3, self.batch, clock=lambda: self.now)
        self.video_body = {"tier": "free", "content_type": "video/mp4", "size_bytes": 100_000_000, "filename": "  dir/Clip 01.mp4  "}

    def create(self, owner="alice", *, opt_in=False):
        response = self.backend.start_upload(owner, {**self.video_body, "allow_admin_review": opt_in})
        return response["video_id"]

    def complete(self, video, owner="alice"):
        count = self.ddb.jobs[video]["part_count"]
        parts = [{"part_number": number, "etag": '"' + "0" * 32 + '"'} for number in range(1, count + 1)]
        self.backend.complete_upload(owner, {"video_id": video, "parts": parts})

    def test_default_consent_private_and_sanitized_filename(self):
        video = self.create()
        record = self.ddb.jobs[video]
        self.assertEqual(record["filename"], "Clip 01.mp4")
        self.assertFalse(record["allow_admin_review"])
        self.assertNotIn("admin_partition", record)
        self.assertEqual(list_review_jobs(self.backend, {})["jobs"], [])
        with self.assertRaises(ApiError):
            self.backend.start_upload("alice", {**self.video_body, "allow_admin_review": "true"})
        with self.assertRaises(ApiError):
            self.backend.start_upload("alice", {**self.video_body, "filename": "\u200b\t"})

    def test_owner_history_paginates_without_leaking_others(self):
        mine = [self.create() for _ in range(3)]
        other = self.create(owner="bob")
        first = list_owner_jobs(self.backend, "alice", {"limit": "2"})
        self.assertEqual(len(first["jobs"]), 2)
        self.assertTrue(first["next_cursor"])
        self.assertNotIn("user_id", first["jobs"][0])
        self.assertNotIn("s3_key", first["jobs"][0])
        second = list_owner_jobs(self.backend, "alice", {"limit": "2", "cursor": first["next_cursor"]})
        self.assertEqual(len(second["jobs"]), 1)
        self.assertFalse(second["next_cursor"])
        self.assertEqual({row["job_id"] for row in first["jobs"] + second["jobs"]}, set(mine))
        self.assertNotIn(other, {row["job_id"] for row in first["jobs"] + second["jobs"]})
        with self.assertRaisesRegex(ApiError, "cursor"):
            list_owner_jobs(self.backend, "bob", {"cursor": first["next_cursor"]})
        with self.assertRaises(ApiError):
            list_owner_jobs(self.backend, "alice", {"limit": "99999"})

    def test_timings_and_expiry_visible_when_known(self):
        video = self.create()
        self.complete(video)
        record = self.ddb.jobs[video]
        self.assertEqual(record["video_expires_at"], self.now + 86400)
        card = list_owner_jobs(self.backend, "alice", {})["jobs"][0]
        self.assertTrue(card["video_available"])
        self.assertIsNone(card["duration_seconds"])
        self.assertEqual(card["filename"], "Clip 01.mp4")
        self.now += 86401
        card = list_owner_jobs(self.backend, "alice", {})["jobs"][0]
        self.assertFalse(card["video_available"])
        self.assertEqual(batch_timings({"createdAt": 1000, "startedAt": 3000, "stoppedAt": 12000}), {
            "batch_created_at_ms": 1000, "batch_started_at_ms": 3000, "batch_stopped_at_ms": 12000,
            "queue_wait_ms": 2000, "batch_run_ms": 9000,
        })

    def test_success_settlement_persists_real_batch_and_worker_timings(self):
        video = self.create()
        self.complete(video)
        self.backend.submit_analysis("alice", {"video_id": video})
        self.s3.objects[self.ddb.jobs[video]["report_key"]] = 9876

        def describe_jobs(**_kwargs):
            return {"jobs": [{
                "status": "SUCCEEDED",
                "createdAt": (self.now - 200) * 1000,
                "startedAt": (self.now - 160) * 1000,
                "stoppedAt": (self.now - 20) * 1000,
            }]}

        sidecar = json.dumps({
            "job_id": video, "analysis_wall_ms": 120000,
            "cpu_time_ms": 181000, "video_duration_ms": 12500,
            "worker_wall_ms": 133000,
        }).encode()
        self.batch.describe_jobs = describe_jobs
        with patch.object(self.s3, "get_object", create=True, return_value={"Body": io.BytesIO(sidecar)}):
            current = self.backend.job_status("alice", video)
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["queue_wait_ms"], 40000)
        self.assertEqual(current["batch_run_ms"], 140000)
        self.assertEqual(current["analysis_wall_ms"], 120000)
        self.assertEqual(current["cpu_time_ms"], 181000)
        self.assertEqual(current["duration_seconds"], 12.5)
        self.assertTrue(current["report_available"])
        card = list_owner_jobs(self.backend, "alice", {})["jobs"][0]
        self.assertEqual(card["duration_seconds"], 12.5)
        self.assertEqual(card["analysis_wall_ms"], 120000)
        self.assertEqual(self.ddb.accounts["alice"]["free_used_bytes"], 100_000_000)
        self.assertEqual(self.ddb.jobs[video]["ttl_epoch"], self.now + self.cfg.terminal_record_grace_seconds + self.cfg.free_report_ttl)

    def test_admin_rejects_email_only_or_unpinned_user(self):
        claims = {"sub": "admin-123", "email": "claimed-admin@example.com", "token_use": "access", "cognito:groups": ["strokesense-admin"]}
        with patch.dict("os.environ", {"ADMIN_COGNITO_SUBS": ""}):
            with self.assertRaises(ApiError):
                require_admin(claims)
        with patch.dict("os.environ", {"ADMIN_COGNITO_SUBS": "admin-123"}):
            self.assertEqual(require_admin(claims), "admin-123")
            for corrupted in (
                {**claims, "cognito:groups": ["users"]},
                {**claims, "token_use": "id"},
                {**claims, "sub": "impostor"},
                {**claims, "cognito:groups": "strokesense-admin"},
            ):
                with self.subTest(corrupted=corrupted), self.assertRaises(ApiError):
                    require_admin(corrupted)

    def test_admin_can_only_view_opt_in_and_audits_every_url(self):
        private = self.create()
        shared = self.create(opt_in=True)
        self.complete(private)
        self.complete(shared)
        visible = list_review_jobs(self.backend, {})["jobs"]
        self.assertEqual([record["job_id"] for record in visible], [shared])
        with self.assertRaises(ApiError):
            admin_video_url(self.backend, "admin-123", private, {"sourceIp": "203.0.113.7"})
        self.assertEqual(self.ddb.admin_audits, {})
        result = admin_video_url(self.backend, "admin-123", shared, {"sourceIp": "203.0.113.7", "userAgent": "Safari"})
        self.assertEqual(result["expires_in"], 60)
        self.assertEqual(result["video_type"], "original")
        self.assertTrue(result["video_url"].startswith("https://"))
        self.assertEqual(len(self.ddb.admin_audits), 1)
        event = next(iter(self.ddb.admin_audits.values()))
        self.assertEqual((event["viewer_sub"], event["owner_sub"], event["job_id"]), ("admin-123", "alice", shared))
        self.assertEqual(event["video_type"], "original")
        self.assertNotIn("video_url", event)
        self.assertNotIn("email", event)

    def test_admin_prefers_annotated_report_video_after_original_expires(self):
        shared = self.create(opt_in=True)
        self.complete(shared)
        record = self.ddb.jobs[shared]
        record.update({
            "status": "succeeded",
            "report_expires_at": self.now + 3 * 86400,
            "video_expires_at": self.now - 1,
        })
        prefix = record["report_key"][:-len("report.json")]
        self.s3.objects[prefix + "annotated.mp4"] = 1_000_000
        manifest = json.dumps({
            "schema_version": "strokesense-private-artifacts-v1",
            "video_available": True,
            "rowers": {},
        }).encode()
        with patch.object(self.s3, "get_object", create=True, return_value={
            "Body": io.BytesIO(manifest), "ContentLength": len(manifest),
        }):
            link = admin_video_url(self.backend, "admin-123", shared, {})
        self.assertEqual(link["video_type"], "annotated")
        self.assertEqual(link["video_expires_at"], record["report_expires_at"])
        self.assertEqual(self.s3.presigned_params["Key"], prefix + "annotated.mp4")
        self.assertEqual(next(iter(self.ddb.admin_audits.values()))["video_type"], "annotated")
        card = list_review_jobs(self.backend, {})["jobs"][0]
        self.assertTrue(card["video_available"])
        self.assertFalse(card["original_video_available"])
        self.assertTrue(card["annotated_video_may_be_available"])

    def test_admin_rejects_missing_annotated_and_expired_original(self):
        shared = self.create(opt_in=True)
        self.complete(shared)
        record = self.ddb.jobs[shared]
        record.update({"status": "succeeded", "report_expires_at": self.now + 100, "video_expires_at": self.now - 1})
        with self.assertRaises(ApiError) as unavailable:
            admin_video_url(self.backend, "admin-123", shared, {})
        self.assertEqual(unavailable.exception.status, 410)
        self.assertFalse(self.ddb.admin_audits)

    def test_owner_revoke_prevents_new_admin_urls_and_other_user_cannot_revoke(self):
        shared = self.create(opt_in=True)
        self.complete(shared)
        stale_index_record = _item(self.ddb.jobs[shared].copy())
        with self.assertRaises(ApiError):
            change_review_consent(self.backend, "mallory", shared, {"allow_admin_review": False})
        self.assertFalse(change_review_consent(self.backend, "alice", shared, {"allow_admin_review": False})["allow_admin_review"])
        self.assertEqual(list_review_jobs(self.backend, {})["jobs"], [])
        # Dynamo GSIs are eventually consistent; stale index records must not
        # leak filenames/metadata after revocation.
        with patch.object(self.ddb, "query", return_value={"Items": [stale_index_record]}):
            self.assertEqual(list_review_jobs(self.backend, {})["jobs"], [])
        with self.assertRaises(ApiError):
            admin_video_url(self.backend, "admin-123", shared, {})

    def test_atomic_consent_check_prevents_race_and_failed_audit_never_returns_url(self):
        shared = self.create(opt_in=True)
        self.complete(shared)
        original = self.ddb.transact_write_items

        def revoked_between_read_and_issue(**kwargs):
            self.ddb.jobs[shared]["allow_admin_review"] = False
            self.ddb.jobs[shared].pop("admin_partition", None)
            return original(**kwargs)

        with patch.object(self.ddb, "transact_write_items", side_effect=revoked_between_read_and_issue):
            with self.assertRaisesRegex(ApiError, "consent"):
                admin_video_url(self.backend, "admin-123", shared, {})
        self.assertFalse(self.ddb.admin_audits)
        self.ddb.jobs[shared]["allow_admin_review"] = True
        self.ddb.jobs[shared]["admin_partition"] = "OPTED_IN"
        with patch.object(self.ddb, "transact_write_items", side_effect=RuntimeError("dynamodb down")):
            with self.assertRaisesRegex(ApiError, "review"):
                admin_video_url(self.backend, "admin-123", shared, {})
        self.assertFalse(self.ddb.admin_audits)

    def test_lambda_enforces_admin_group_plus_allowlist_on_real_route(self):
        shared = self.create(opt_in=True)
        self.complete(shared)
        event = {
            "rawPath": f"/admin/videos/{shared}",
            "requestContext": {"http": {"method": "GET", "sourceIp": "127.0.0.1"}, "authorizer": {"jwt": {"claims": {
                "sub": "admin-123", "token_use": "access", "cognito:groups": ["strokesense-admin"],
            }}}},
        }
        with patch("aws_app.handler._build_service", return_value=self.backend):
            with patch.dict("os.environ", {"ADMIN_COGNITO_SUBS": ""}):
                self.assertEqual(lambda_handler(event, None)["statusCode"], 403)
            with patch.dict("os.environ", {"ADMIN_COGNITO_SUBS": "admin-123"}):
                self.assertEqual(lambda_handler(event, None)["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
