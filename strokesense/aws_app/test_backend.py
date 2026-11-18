"""Offline tests for the AWS scaffold; no credentials or AWS resources used."""

from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from aws_app.core import (
    ApiError,
    AwsBackend,
    Settings,
    UPLOAD_TTL_SECONDS,
    _decode,
    _item,
)
from aws_app.handler import lambda_handler
from aws_app.reconcile import reconcile_due, lambda_handler as reconciliation_lambda_handler


class FakeAwsError(Exception):
    def __init__(self, code: str, reasons: list[dict] | None = None):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "CancellationReasons": reasons or []}


class MemoryDynamo:
    """Only the DynamoDB operations and atomic conditions used by this service."""

    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.transactions: list[list[dict]] = []

    def put_item(self, **kwargs):
        account = _decode(kwargs["Item"])
        uid = account["user_id"]
        if uid in self.accounts:
            raise FakeAwsError("ConditionalCheckFailedException")
        self.accounts[uid] = account

    def get_item(self, **kwargs):
        job_id = kwargs["Key"]["job_id"]["S"]
        return {"Item": _item(self.jobs[job_id])} if job_id in self.jobs else {}

    def query(self, **kwargs):
        values = kwargs["ExpressionAttributeValues"]
        now = int(values[":now"]["N"])
        if kwargs["IndexName"] == "user_id-created_at-index":
            uid = values[":uid"]["S"]
            return {"Items": [
                _item(job)
                for job in self.jobs.values()
                if job["user_id"] == uid
                and job["status"] in ("uploading", "uploaded")
                and job["expires_at"] < now
            ]}
        assert kwargs["IndexName"] == "status-expires_at-index"
        state = values[":state"]["S"]
        records = sorted(
            (job for job in self.jobs.values() if job["status"] == state and job["expires_at"] < now),
            key=lambda job: (job["expires_at"], job["job_id"]),
        )
        if kwargs.get("ExclusiveStartKey"):
            last = kwargs["ExclusiveStartKey"]
            marker = (int(last["expires_at"]["N"]), last["job_id"]["S"])
            records = [job for job in records if (job["expires_at"], job["job_id"]) > marker]
        limit = kwargs.get("Limit", len(records))
        page = records[:limit]
        result = {"Items": [_item(job) for job in page]}
        if len(records) > limit:
            result["LastEvaluatedKey"] = {
                "job_id": {"S": page[-1]["job_id"]},
                "expires_at": {"N": str(page[-1]["expires_at"])},
            }
        return result

    @staticmethod
    def _conditional_failure():
        raise FakeAwsError("TransactionCanceledException", [{"Code": "ConditionalCheckFailed"}])

    def transact_write_items(self, **kwargs):
        accounts = copy.deepcopy(self.accounts)
        jobs = copy.deepcopy(self.jobs)
        changes = kwargs["TransactItems"]
        for action in changes:
            if "Put" in action:
                record = _decode(action["Put"]["Item"])
                if record["job_id"] in jobs:
                    self._conditional_failure()
                jobs[record["job_id"]] = record
                continue
            update = action["Update"]
            expression = update["UpdateExpression"]
            values = update["ExpressionAttributeValues"]
            if update["TableName"] == "users":
                user_id = update["Key"]["user_id"]["S"]
                account = accounts[user_id]
                amount = int(values[":amount"]["N"])
                is_free = "free_" in expression
                prefix = "free_" if is_free else "paid_credits_"
                available = prefix + ("available_bytes" if is_free else "available")
                reserved = prefix + ("reserved_bytes" if is_free else "reserved")
                used = prefix + ("used_bytes" if is_free else "used")
                if expression.startswith(f"SET {available}"):
                    if account[available] < amount:
                        self._conditional_failure()
                    account[available] -= amount
                    account[reserved] += amount
                elif f"{used} = {used} + :amount" in expression:
                    if account[reserved] < amount:
                        self._conditional_failure()
                    account[reserved] -= amount
                    account[used] += amount
                else:
                    if account[reserved] < amount:
                        self._conditional_failure()
                    account[reserved] -= amount
                    account[available] += amount
            else:
                job_id = update["Key"]["job_id"]["S"]
                record = jobs[job_id]
                if record["user_id"] != values[":uid"]["S"]:
                    self._conditional_failure()
                expected = [value["S"] for key, value in values.items() if key.startswith(":state")]
                if record["status"] not in expected:
                    self._conditional_failure()
                record["status"] = values[":next"]["S"]
                if ":ttl" in values:
                    record["ttl_epoch"] = int(values[":ttl"]["N"])
                if ":report_expires" in values:
                    record["report_expires_at"] = int(values[":report_expires"]["N"])
        self.transactions.append(changes)
        self.accounts = accounts
        self.jobs = jobs

    def update_item(self, **kwargs):
        job_id = kwargs["Key"]["job_id"]["S"]
        job = self.jobs[job_id]
        values = kwargs["ExpressionAttributeValues"]
        if job["user_id"] != values[":uid"]["S"]:
            raise FakeAwsError("ConditionalCheckFailedException")
        expected = None
        if ":uploading" in values:
            expected = "uploading"
        elif ":submitting" in values and ":submitted" in values:
            expected = "submitting"
        elif ":submitting" in values:
            expected = "uploaded"
        elif ":uploaded" in values and ":updated" not in values:
            expected = "submitting"
        elif ":uploaded" in values:
            expected = "uploading"
        if expected and job["status"] != expected:
            raise FakeAwsError("ConditionalCheckFailedException")
        if ":upload_id" in values:
            job["s3_upload_id"] = values[":upload_id"]["S"]
        if ":uploaded" in values:
            job["status"] = "uploaded"
        if ":submitting" in values and ":submitted" not in values:
            job["status"] = "submitting"
        if ":submitted" in values:
            job["status"] = "submitted"
            job["batch_job_id"] = values[":batch_id"]["S"]


class FakeS3:
    def __init__(self):
        self.objects: dict[str, int] = {}
        self.completed: list[str] = []
        self.deleted: list[str] = []
        self.aborted: list[str] = []
        self.final_size: int = 100_000_000
        self.presigned_params: dict = {}

    def create_multipart_upload(self, **kwargs):
        return {"UploadId": "fake-upload-id"}

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs["Key"])

    def complete_multipart_upload(self, **kwargs):
        self.completed.append(kwargs["Key"])
        self.objects[kwargs["Key"]] = self.final_size

    def head_object(self, **kwargs):
        key = kwargs["Key"]
        if key not in self.objects:
            raise FakeAwsError("NoSuchKey")
        return {"ContentLength": self.objects[key]}

    def delete_object(self, **kwargs):
        key = kwargs["Key"]
        self.deleted.append(key)
        self.objects.pop(key, None)

    def generate_presigned_url(self, operation, **kwargs):
        self.presigned_params = kwargs["Params"]
        return f"https://signed.example.invalid/{operation}/{kwargs['Params']['Key']}"


class FakeBatch:
    status = "RUNNING"

    def submit_job(self, **kwargs):
        return {"jobId": "fake-batch-job"}

    def describe_jobs(self, **kwargs):
        return {"jobs": [{"status": self.status}]}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.ddb = MemoryDynamo()
        self.s3 = FakeS3()
        self.batch = FakeBatch()
        self.now = 1_800_000_000
        self.cfg = Settings("video-bucket", "users", "jobs", batch_queue="cpu-queue", batch_definition="cpu-def")
        self.backend = AwsBackend(self.cfg, self.ddb, self.s3, self.batch, clock=lambda: self.now)
        self.free_body = {"content_type": "video/mp4", "size_bytes": 100_000_000, "tier": "free"}

    def _complete(self, video_id):
        record = self.ddb.jobs[video_id]
        count = record["part_count"]
        parts = [{"part_number": part, "etag": '"' + "a" * 32 + '"'} for part in range(1, count + 1)]
        return self.backend.complete_upload("alice", {"video_id": video_id, "parts": parts})

    def test_atomic_lifetime_quota_and_abort_refund(self):
        ids = [self.backend.start_upload("alice", self.free_body)["video_id"] for _ in range(3)]
        account = self.ddb.accounts["alice"]
        self.assertEqual((account["free_available_bytes"], account["free_reserved_bytes"], account["free_used_bytes"]), (0, 300_000_000, 0))
        with self.assertRaises(ApiError) as blocked:
            self.backend.start_upload("alice", self.free_body)
        self.assertEqual(blocked.exception.code, "free_quota_exhausted")
        self.assertEqual(len(self.ddb.jobs), 3)  # Put and quota update share transaction.
        self.backend.abort_upload("alice", {"video_id": ids[0]})
        self.backend.abort_upload("alice", {"video_id": ids[0]})  # idempotent
        self.assertEqual(account["free_reserved_bytes"], 300_000_000)  # Snapshot prior to transaction.
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 100_000_000)
        self.backend.start_upload("alice", self.free_body)
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 0)

    def test_unconfigured_paid_fails_closed_and_server_side_credits(self):
        with self.assertRaises(ApiError) as denied:
            self.backend.start_upload("alice", {"content_type": "video/mp4", "size_bytes": 1, "tier": "paid"})
        self.assertEqual(denied.exception.code, "billing_not_configured")
        paid = AwsBackend(Settings("video-bucket", "users", "jobs", paid_billing_enabled=True), self.ddb, self.s3, clock=lambda: self.now)
        paid._account("alice")
        self.ddb.accounts["alice"]["paid_credits_available"] = 1  # Simulate future verified webhook.
        video = paid.start_upload("alice", {"content_type": "video/mp4", "size_bytes": 750_000_000, "tier": "paid"})
        self.assertEqual(self.ddb.accounts["alice"]["paid_credits_reserved"], 1)
        self.assertEqual(video["part_count"], 90)
        with self.assertRaises(ApiError) as insufficient:
            paid.start_upload("alice", {"content_type": "video/mp4", "size_bytes": 1, "tier": "paid"})
        self.assertEqual(insufficient.exception.code, "paid_credits_exhausted")
        with self.assertRaises(ApiError) as too_large:
            paid.start_upload("alice", {"content_type": "video/mp4", "size_bytes": 750_000_001, "tier": "paid"})
        self.assertEqual(too_large.exception.status, 413)

    def test_free_per_video_limit_is_decimal_100mb(self):
        for size in (100_000_001, -1, "100000000", True, 0):
            with self.subTest(size=size), self.assertRaises(ApiError):
                self.backend.start_upload("alice", {**self.free_body, "size_bytes": size})

    def test_other_user_cannot_presign_complete_abort_or_view(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        operations = [
            lambda: self.backend.presign_part("mallory", {"video_id": video, "part_number": 1}),
            lambda: self.backend.complete_upload("mallory", {"video_id": video, "parts": []}),
            lambda: self.backend.abort_upload("mallory", {"video_id": video}),
            lambda: self.backend.job_status("mallory", video),
            lambda: self.backend.report_url("mallory", video),
        ]
        for operation in operations:
            with self.assertRaises(ApiError) as denied:
                operation()
            self.assertEqual(denied.exception.status, 404)

    def test_multipart_parts_are_bounded_and_completion_size_verified(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        url = self.backend.presign_part("alice", {"video_id": video, "part_number": 1})
        self.assertIn("/upload_part/", url["url"])
        self.assertEqual(url["required_size_bytes"], 8 * 1024 * 1024)
        self.assertEqual(self.s3.presigned_params["ContentLength"], 8 * 1024 * 1024)
        self.assertEqual(
            self.backend.presign_part("alice", {"video_id": video, "part_number": 12})["required_size_bytes"],
            100_000_000 - 11 * 8 * 1024 * 1024,
        )
        with self.assertRaises(ApiError):
            self.backend.presign_part("alice", {"video_id": video, "part_number": 999})
        self.s3.final_size = 99_999_999
        with self.assertRaises(ApiError) as mismatch:
            self._complete(video)
        self.assertEqual(mismatch.exception.code, "upload_size_mismatch")
        self.assertEqual(self.ddb.jobs[video]["status"], "aborted")
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 300_000_000)
        self.assertTrue(self.s3.deleted)

    def test_stale_incomplete_upload_refunds_on_next_request(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self.now += UPLOAD_TTL_SECONDS + 1
        self.backend.start_upload("alice", self.free_body)
        self.assertEqual(self.ddb.jobs[old]["status"], "aborted")
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_stale_completed_upload_without_analysis_refunds(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.now += UPLOAD_TTL_SECONDS + 1
        self.backend.start_upload("alice", self.free_body)
        self.assertEqual(self.ddb.jobs[old]["status"], "aborted")
        self.assertIn(self.ddb.jobs[old]["s3_key"], self.s3.deleted)
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 200_000_000)

    def test_success_charges_only_after_report_and_enforces_expiry(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        submitted = self.backend.submit_analysis("alice", {"video_id": video})
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(self.ddb.accounts["alice"]["free_used_bytes"], 0)
        self.assertEqual(self.backend.job_status("alice", video)["status"], "running")
        self.batch.status = "SUCCEEDED"
        self.s3.objects[self.ddb.jobs[video]["report_key"]] = 1280
        self.assertEqual(self.backend.job_status("alice", video)["status"], "succeeded")
        self.assertEqual(self.backend.job_status("alice", video)["status"], "succeeded")  # no double-consume
        self.assertEqual(self.ddb.accounts["alice"]["free_used_bytes"], 100_000_000)
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 0)
        self.assertIn("/get_object/", self.backend.report_url("alice", video)["download_url"])
        self.now += 72 * 3600 + 1
        with self.assertRaises(ApiError) as expired:
            self.backend.report_url("alice", video)
        self.assertEqual(expired.exception.status, 410)

    def test_missing_report_after_batch_success_refunds_as_failure(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        self.backend.submit_analysis("alice", {"video_id": video})
        self.batch.status = "SUCCEEDED"
        self.assertEqual(self.backend.job_status("alice", video)["status"], "failed")
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 300_000_000)

    def test_temporary_s3_error_does_not_refund_successful_batch(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        self.backend.submit_analysis("alice", {"video_id": video})
        self.batch.status = "SUCCEEDED"
        with patch.object(self.s3, "head_object", side_effect=FakeAwsError("ServiceUnavailable")):
            with self.assertRaises(FakeAwsError):
                self.backend.job_status("alice", video)
        self.assertEqual(self.ddb.jobs[video]["status"], "submitted")
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_batch_failure_refunds_quota_once(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        self.backend.submit_analysis("alice", {"video_id": video})
        self.batch.status = "FAILED"
        self.assertEqual(self.backend.job_status("alice", video)["status"], "failed")
        self.assertEqual(self.backend.job_status("alice", video)["status"], "failed")
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 300_000_000)

    def test_terminal_records_have_ttl_pending_records_do_not(self):
        uploading = self.backend.start_upload("alice", self.free_body)["video_id"]
        self.assertNotIn("ttl_epoch", self.ddb.jobs[uploading])
        self.backend.abort_upload("alice", {"video_id": uploading})
        self.assertGreater(self.ddb.jobs[uploading]["ttl_epoch"], self.now)
        succeeded = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(succeeded)
        self.backend.submit_analysis("alice", {"video_id": succeeded})
        self.batch.status = "SUCCEEDED"
        self.s3.objects[self.ddb.jobs[succeeded]["report_key"]] = 1024
        self.backend.job_status("alice", succeeded)
        self.assertGreater(self.ddb.jobs[succeeded]["ttl_epoch"], self.ddb.jobs[succeeded]["report_expires_at"])


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        BackendTests.setUp(self)

    def _complete(self, video_id):
        return BackendTests._complete(self, video_id)

    def test_background_refunds_abandoned_upload_without_polling(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self.now += UPLOAD_TTL_SECONDS + 1
        first = reconcile_due(self.backend)
        self.assertEqual(first["aborted"], 1)
        self.assertEqual(self.ddb.jobs[old]["status"], "aborted")
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 300_000_000)
        second = reconcile_due(self.backend)
        self.assertEqual(second["aborted"], 0)

    def test_background_refunds_uploaded_clip_without_analysis(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.now += UPLOAD_TTL_SECONDS + 1
        result = reconcile_due(self.backend)
        self.assertEqual(result["aborted"], 1)
        self.assertEqual(self.ddb.jobs[old]["status"], "aborted")
        self.assertIn(self.ddb.jobs[old]["s3_key"], self.s3.deleted)

    def test_background_refunds_failed_batch_without_browser_poll(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.backend.submit_analysis("alice", {"video_id": old})
        self.batch.status = "FAILED"
        self.now += UPLOAD_TTL_SECONDS + 1
        result = reconcile_due(self.backend)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.ddb.jobs[old]["status"], "failed")
        self.assertEqual(self.ddb.accounts["alice"]["free_available_bytes"], 300_000_000)
        self.assertEqual(reconcile_due(self.backend)["failed"], 0)

    def test_background_consumes_only_verified_success(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.backend.submit_analysis("alice", {"video_id": old})
        self.s3.objects[self.ddb.jobs[old]["report_key"]] = 1024
        self.batch.status = "SUCCEEDED"
        self.now += UPLOAD_TTL_SECONDS + 1
        result = reconcile_due(self.backend)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(self.ddb.accounts["alice"]["free_used_bytes"], 100_000_000)

    def test_background_does_not_refund_running_batch(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.backend.submit_analysis("alice", {"video_id": old})
        self.batch.status = "RUNNING"
        self.now += UPLOAD_TTL_SECONDS + 1
        result = reconcile_due(self.backend)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(self.ddb.jobs[old]["status"], "submitted")
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_background_preserves_ambiguous_submit(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.ddb.jobs[old]["status"] = "submitting"
        self.now += UPLOAD_TTL_SECONDS + 1
        with patch("aws_app.reconcile.LOGGER.warning"):
            result = reconcile_due(self.backend)
        self.assertEqual(result["manual_review"], 1)
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_background_preserves_submitted_record_without_batch_id(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.ddb.jobs[old]["status"] = "submitted"
        self.now += UPLOAD_TTL_SECONDS + 1
        with patch("aws_app.reconcile.LOGGER.warning"):
            result = reconcile_due(self.backend)
        self.assertEqual(result["manual_review"], 1)
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_background_transient_head_failure_keeps_reservation(self):
        old = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(old)
        self.backend.submit_analysis("alice", {"video_id": old})
        self.batch.status = "SUCCEEDED"
        self.now += UPLOAD_TTL_SECONDS + 1
        with patch.object(self.s3, "head_object", side_effect=FakeAwsError("ServiceUnavailable")):
            with patch("aws_app.reconcile.LOGGER.exception"):
                result = reconcile_due(self.backend)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(self.ddb.jobs[old]["status"], "submitted")
        self.assertEqual(self.ddb.accounts["alice"]["free_reserved_bytes"], 100_000_000)

    def test_background_limits_each_state_batch(self):
        for _ in range(3):
            self.backend.start_upload("alice", self.free_body)
        self.now += UPLOAD_TTL_SECONDS + 1
        result = reconcile_due(self.backend, per_state_limit=2)
        self.assertEqual(result["aborted"], 2)
        self.assertEqual(result["truncated_states"], 1)
        second = reconcile_due(self.backend, per_state_limit=2)
        self.assertEqual(second["aborted"], 1)

    def test_reconcile_lambda_rejects_untrusted_direct_invocation(self):
        with self.assertRaises(ValueError):
            reconciliation_lambda_handler({}, None)

    def test_abort_race_with_submit_does_not_claim_quota_refund(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)

        def competing_submit(**_kwargs):
            self.ddb.jobs[video]["status"] = "submitting"
            raise FakeAwsError("TransactionCanceledException", [{"Code": "ConditionalCheckFailed"}])

        with patch.object(self.ddb, "transact_write_items", side_effect=competing_submit):
            with self.assertRaises(ApiError) as race:
                self.backend.abort_upload("alice", {"video_id": video})
        self.assertEqual(race.exception.status, 409)
        self.assertEqual(self.ddb.jobs[video]["status"], "submitting")

    def test_losing_settlement_race_does_not_report_opposite_outcome(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        self.backend.submit_analysis("alice", {"video_id": video})

        def competing_failure(**_kwargs):
            self.ddb.jobs[video]["status"] = "failed"
            raise FakeAwsError("TransactionCanceledException", [{"Code": "ConditionalCheckFailed"}])

        with patch.object(self.ddb, "transact_write_items", side_effect=competing_failure):
            with self.assertRaises(ApiError) as race:
                self.backend._settle(self.ddb.jobs[video], succeeded=True)
        self.assertEqual(race.exception.status, 409)
        self.assertEqual(race.exception.code, "job_changed")

    def test_completion_race_with_abort_cleans_up_completed_object(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        real_update = self.ddb.update_item

        def abort_while_completing(**kwargs):
            if "SET #state = :uploaded" in kwargs["UpdateExpression"]:
                self.ddb.jobs[video]["status"] = "aborted"
                raise FakeAwsError("ConditionalCheckFailedException")
            return real_update(**kwargs)

        with patch.object(self.ddb, "update_item", side_effect=abort_while_completing):
            with self.assertRaises(ApiError) as race:
                self._complete(video)
        self.assertEqual(race.exception.code, "upload_changed")
        self.assertIn(self.ddb.jobs[video]["s3_key"], self.s3.deleted)

    def test_compute_unconfigured_never_submits(self):
        video = self.backend.start_upload("alice", self.free_body)["video_id"]
        self._complete(video)
        backend = AwsBackend(Settings("video-bucket", "users", "jobs"), self.ddb, self.s3, clock=lambda: self.now)
        with self.assertRaises(ApiError) as missing:
            backend.submit_analysis("alice", {"video_id": video})
        self.assertEqual(missing.exception.code, "compute_not_configured")
        self.assertEqual(self.ddb.jobs[video]["status"], "uploaded")


class HandlerTests(unittest.TestCase):
    def event(self, path="/uploads/start", method="POST", user="alice", body=None):
        return {
            "version": "2.0",
            "rawPath": path,
            "requestContext": {
                "http": {"method": method},
                "authorizer": {"jwt": {"claims": {"sub": user}}} if user is not None else {},
            },
            "body": json.dumps(body or {}),
        }

    def test_missing_gateway_jwt_claims_denied(self):
        with patch("aws_app.handler._build_service") as make:
            result = lambda_handler(self.event(user=None), None)
        self.assertEqual(result["statusCode"], 401)
        make.assert_not_called()

    def test_health_needs_no_credentials_and_does_not_connect_to_aws(self):
        with patch("aws_app.handler._build_service") as make:
            result = lambda_handler(self.event(path="/health", method="GET", user=None), None)
        self.assertEqual(result["statusCode"], 200)
        make.assert_not_called()

    def test_route_passes_authorizer_subject_not_user_body(self):
        with patch("aws_app.handler._build_service") as make:
            make.return_value.start_upload.return_value = {"video_id": "good"}
            result = lambda_handler(self.event(body={"user_id": "mallory", "size_bytes": 2}), None)
        self.assertEqual(result["statusCode"], 201)
        make.return_value.start_upload.assert_called_once_with("alice", {"user_id": "mallory", "size_bytes": 2})

    def test_invalid_body_is_rejected(self):
        event = self.event()
        event["body"] = "not JSON"
        with patch("aws_app.handler._build_service"):
            result = lambda_handler(event, None)
        self.assertEqual(result["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
