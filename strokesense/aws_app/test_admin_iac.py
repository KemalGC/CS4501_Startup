"""Offline policy/route guardrails for the new admin endpoint.

These assertions supplement, but do not replace, Terraform validate and an
AWS IAM integration test with a real API Gateway/Cognito authorizer.
"""

from pathlib import Path
import re
import unittest


INFRA = Path(__file__).resolve().parents[2] / "infra" / "aws"


def _policy_statement(text: str, sid: str) -> str:
    match = re.search(r'\bsid\s*=\s*"' + re.escape(sid) + r'"', text)
    if match is None:
        raise AssertionError(f"Policy statement missing: {sid}")
    start = match.start()
    return text[start:text.find("\n  }", start)]


class AdminInfrastructureContractTests(unittest.TestCase):
    def test_transact_authority_on_both_job_condition_and_audit_put(self):
        policy = (INFRA / "iam.tf").read_text(encoding="utf-8")
        jobs = _policy_statement(policy, "ReadWriteQuotaAndJobs")
        audit = _policy_statement(policy, "AuditAdminReviewWithConditionalConsent")
        for required in ("dynamodb:TransactWriteItems", "dynamodb:ConditionCheckItem", "aws_dynamodb_table.jobs.arn"):
            self.assertIn(required, jobs)
        for required in ("dynamodb:TransactWriteItems", "dynamodb:PutItem", "aws_dynamodb_table.admin_access_audit.arn"):
            self.assertIn(required, audit)

    def test_admin_routes_require_gateway_jwt_authorizer(self):
        api = (INFRA / "api.tf").read_text(encoding="utf-8")
        for route in ("GET /admin/jobs", "GET /admin/videos/{id}", "GET /analysis/jobs", "POST /analysis/jobs/{id}/review"):
            self.assertIn(f'"{route}"', api)
        self.assertIn('resource "aws_apigatewayv2_route" "authenticated"', api)
        self.assertIn('authorization_type = "JWT"', api)

    def test_consent_gsi_sparse_and_audit_has_ttl(self):
        database = (INFRA / "dynamodb.tf").read_text(encoding="utf-8")
        self.assertIn('name            = "admin_partition-created_at-index"', database)
        self.assertIn('resource "aws_dynamodb_table" "admin_access_audit"', database)
        self.assertIn('attribute_name = "ttl_epoch"', database)
        cognito = (INFRA / "cognito.tf").read_text(encoding="utf-8")
        self.assertIn('resource "aws_cognito_user_group" "strokesense_admin"', cognito)


if __name__ == "__main__":
    unittest.main()
