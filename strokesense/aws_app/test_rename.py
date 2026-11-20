"""Authenticated rename of an existing analysis, with no media/key changes."""
from __future__ import annotations
import unittest
from unittest.mock import MagicMock, patch

from aws_app.core import ApiError, AwsBackend, Settings, _item
from aws_app.handler import lambda_handler
from aws_app.library import rename_owned_job

class RenameTests(unittest.TestCase):
    def setUp(self):
        self.job_id = "a" * 32
        self.record = {"job_id": self.job_id, "user_id": "owner", "status": "succeeded",
                       "filename": "original.mp4", "s3_key": "uploads/owned/original.mp4",
                       "report_key": "reports/free/owned/report.json"}
        self.ddb = MagicMock()
        self.ddb.get_item.side_effect = lambda **_kwargs: {"Item": _item(self.record)}
        self.svc = AwsBackend(Settings("bucket", "users", "jobs"), self.ddb, MagicMock())

    def test_owner_can_rename_without_touching_media(self):
        result = rename_owned_job(self.svc, "owner", self.job_id, {"filename": "Practice / New name"})
        self.assertEqual(result["filename"], "New name")
        params = self.ddb.update_item.call_args.kwargs
        self.assertIn("user_id = :uid", params["ConditionExpression"])
        self.assertIn("attribute_exists(job_id)", params["ConditionExpression"])
        self.assertIn("#state <> :deleting", params["ConditionExpression"])
        self.assertEqual(params["ExpressionAttributeValues"][":filename"]["S"], "New name")
        self.assertNotIn("s3_key", params["UpdateExpression"])
        self.svc.s3.assert_not_called()

    def test_other_user_cannot_rename(self):
        with self.assertRaises(ApiError) as error:
            rename_owned_job(self.svc, "stranger", self.job_id, {"filename": "Sneaky"})
        self.assertEqual(error.exception.status, 404)
        self.ddb.update_item.assert_not_called()

    def test_bad_names_and_deleting_jobs_are_rejected(self):
        for bad in (None, "", " ", "\u200b\t", 123, "a" * 129):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                rename_owned_job(self.svc, "owner", self.job_id, {"filename": bad})
        self.record["status"] = "deleting"
        with self.assertRaises(ApiError) as error:
            rename_owned_job(self.svc, "owner", self.job_id, {"filename": "Renamed"})
        self.assertEqual(error.exception.status, 404)
        self.ddb.update_item.assert_not_called()

    def test_rename_endpoint_requires_signed_in_owner(self):
        event = {"rawPath": f"/analysis/jobs/{self.job_id}/rename",
                 "requestContext": {"http": {"method": "POST"}},
                 "body": '{"filename":"Test video"}'}
        with patch("aws_app.handler._build_service", return_value=self.svc):
            self.assertEqual(lambda_handler(event, None)["statusCode"], 401)
            event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": "owner"}}}
            self.assertEqual(lambda_handler(event, None)["statusCode"], 200)
            event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] = "stranger"
            self.assertEqual(lambda_handler(event, None)["statusCode"], 404)

if __name__ == "__main__":
    unittest.main()
