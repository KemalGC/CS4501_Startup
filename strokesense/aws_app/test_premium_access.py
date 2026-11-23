"""No-network tests for Premium identity, admin grants, audit, and revocation."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from aws_app.core import ApiError, AwsBackend, Settings, _decode, _is_conditional
from aws_app.handler import lambda_handler
from aws_app.paid_access import evaluate_paid_membership
from aws_app.premium_access import (
    account_access, change_premium_access, lookup_premium_user, require_premium_access,
)
from aws_app.test_backend import FakeAwsError, FakeBatch, FakeS3, MemoryDynamo


OWNER = "11111111-1111-4111-8111-111111111111"
MEMBER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
MISSING = "44444444-4444-4444-8444-444444444444"


class CognitoDirectory:
    def __init__(self):
        self.users = {}
        self.list_calls = []
        self.get_calls = []
        self.pages = None
        self.list_snapshot = None

    def add(self, sub, email, *, verified=True, enabled=True):
        username = "Google_" + sub.replace("-", "")
        self.users[username] = {
            "Username": username, "Enabled": enabled, "UserStatus": "EXTERNAL_PROVIDER",
            "UserAttributes": [
                {"Name": "sub", "Value": sub},
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true" if verified else "false"},
            ],
        }
        return username

    def admin_get_user(self, **kwargs):
        self.get_calls.append(kwargs)
        if kwargs["Username"] not in self.users:
            raise FakeAwsError("UserNotFoundException")
        return copy.deepcopy(self.users[kwargs["Username"]])

    def list_users(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.pages is not None:
            return copy.deepcopy(self.pages[int(kwargs.get("PaginationToken", "0"))])
        attribute, encoded = kwargs["Filter"].split(" = ", 1)
        expected = json.loads(encoded)
        source = self.list_snapshot if self.list_snapshot is not None else self.users
        users = [user for user in source.values() if any(
            a["Name"] == attribute and a["Value"] == expected for a in user["UserAttributes"]
        )]
        return {"Users": copy.deepcopy(users)}


class PremiumDynamo(MemoryDynamo):
    def __init__(self):
        super().__init__()
        self.fail_audit = False
        self.before_transaction = None

    def transact_write_items(self, **kwargs):
        changes = kwargs["TransactItems"]
        first = changes[0].get("Update", {})
        if "premium_access_granted =" not in first.get("UpdateExpression", ""):
            return super().transact_write_items(**kwargs)
        if self.before_transaction:
            callback, self.before_transaction = self.before_transaction, None
            callback()
        accounts, audits = copy.deepcopy(self.accounts), copy.deepcopy(self.admin_audits)
        update, audit_put = changes[0]["Update"], changes[1]["Put"]
        uid = update["Key"]["user_id"]["S"]
        record = accounts.get(uid, {})
        condition = update["ConditionExpression"]
        values = _decode(update["ExpressionAttributeValues"])
        if record.get("user_id") != values[":subject"]:
            self._conditional_failure()
        for field in ("premium_access_granted", "premium_access_version"):
            if f"attribute_not_exists({field})" in condition and field in record:
                self._conditional_failure()
        if ":previous_version" in values and record.get("premium_access_version") != values[":previous_version"]:
            self._conditional_failure()
        if ":previous_granted" in values and record.get("premium_access_granted") != values[":previous_granted"]:
            self._conditional_failure()
        for assignment in update["UpdateExpression"][4:].split(", "):
            key, value_key = assignment.split(" = ")
            record[key] = values[value_key]
        audit = _decode(audit_put["Item"])
        if audit["audit_id"] in audits:
            self._conditional_failure()
        if self.fail_audit:
            raise FakeAwsError("AccessDeniedException")
        audits[audit["audit_id"]] = audit
        self.accounts, self.admin_audits = accounts, audits
        self.transactions.append(copy.deepcopy(changes))


class PremiumAccessTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.ddb, self.cognito = PremiumDynamo(), CognitoDirectory()
        self.owner_username = self.cognito.add(OWNER, "kemalgcortuk@gmail.com")
        self.member_username = self.cognito.add(MEMBER, "member@example.com")
        self.other_username = self.cognito.add(OTHER, "other@example.com")
        self.backend = AwsBackend(
            Settings("media", "users", "jobs", "cpu-queue", "cpu-definition",
                     admin_audit_table="audit", cognito_user_pool_id="us-east-1_test",
                     premium_owner_sub=OWNER),
            self.ddb, FakeS3(), FakeBatch(), clock=lambda: self.now, cognito=self.cognito,
        )
        self.admin = self.claims(OWNER)
        self.admin["cognito:groups"] = ["strokesense-admin"]
        env = patch.dict("os.environ", {"ADMIN_COGNITO_SUBS": OWNER})
        env.start()
        self.addCleanup(env.stop)

    def claims(self, sub):
        return {"sub": sub, "username": "Google_" + sub.replace("-", ""), "token_use": "access"}

    def change(self, enabled=True, sub=MEMBER, **extra):
        return change_premium_access(self.backend, self.admin, sub,
                                     {"enabled": enabled, "reason": "Premium pilot access", **extra})

    def assert_api_error(self, code, callable_, *args, **kwargs):
        with self.assertRaises(ApiError) as error:
            callable_(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_owner_pin_grants_once_and_preserves_existing_quota(self):
        self.backend._account(OWNER)
        self.ddb.accounts[OWNER].update(free_available_bytes=7, free_used_bytes=99, paid_credits_available=2)
        first = account_access(self.backend, self.admin)
        second = account_access(self.backend, self.admin)
        self.assertEqual(first, second)
        self.assertTrue(first["premium_access"]["granted"])
        self.assertTrue(first["is_admin"])
        self.assertTrue(first["premium_access"]["owner_protected"])
        self.assertFalse(first["premium_access"]["available"])
        self.assertEqual(first["premium_access"]["reason"], "gpu_not_ready")
        self.assertEqual(first["premium_access"]["source"], "owner")
        account = self.ddb.accounts[OWNER]
        self.assertEqual((account["free_available_bytes"], account["free_used_bytes"], account["paid_credits_available"]), (7, 99, 2))
        self.assertEqual(len(self.ddb.admin_audits), 1)
        audit = next(iter(self.ddb.admin_audits.values()))
        self.assertEqual((audit["action"], audit["actor_sub"], audit["target_sub"]), ("premium_owner_bootstrapped", OWNER, OWNER))
        self.assertEqual(audit["ttl_epoch"], self.now + 90 * 86400)
        self.assertFalse(self.backend.cfg.paid_gpu_enabled)
        self.assertFalse(self.backend.cfg.paid_billing_enabled)

    def test_email_claim_or_reused_owner_email_does_not_grant_access(self):
        self.cognito.users[self.member_username]["UserAttributes"][1]["Value"] = "kemalgcortuk@gmail.com"
        claims = {**self.claims(MEMBER), "email": "kemalgcortuk@gmail.com", "email_verified": True}
        view = account_access(self.backend, claims)
        self.assertFalse(view["premium_access"]["granted"])
        self.assertFalse(view["is_admin"])
        self.assertEqual(self.ddb.accounts, {})
        self.assertEqual(self.ddb.admin_audits, {})

    def test_owner_grant_alone_does_not_create_admin_role(self):
        view = account_access(self.backend, self.claims(OWNER))
        self.assertTrue(view["premium_access"]["granted"])
        self.assertFalse(view["is_admin"])
        self.assert_api_error("admin_forbidden", change_premium_access, self.backend, self.claims(OWNER), MEMBER,
                              {"enabled": True, "reason": "Not an admin"})

    def test_current_identity_requires_access_token_and_matching_fresh_subject(self):
        for claims in (
            {**self.admin, "token_use": "id"},
            {"sub": OWNER, "token_use": "access", "cognito:username": self.owner_username},
        ):
            self.assert_api_error("unauthorized", account_access, self.backend, claims)
        self.assert_api_error("premium_identity_unverified", account_access, self.backend,
                              {**self.admin, "username": self.member_username})
        for field, value in (("Enabled", False), ("UserStatus", "FORCE_CHANGE_PASSWORD")):
            with self.subTest(field=field):
                original = self.cognito.users[self.owner_username][field]
                self.cognito.users[self.owner_username][field] = value
                self.assert_api_error("premium_identity_unverified", account_access, self.backend, self.admin)
                self.cognito.users[self.owner_username][field] = original
        self.cognito.users[self.owner_username]["UserAttributes"][2]["Value"] = "false"
        self.assert_api_error("premium_identity_unverified", account_access, self.backend, self.admin)
        self.assertEqual(self.ddb.admin_audits, {})

    def test_grant_lookup_and_revoke_are_audited_and_do_not_create_credits(self):
        found = lookup_premium_user(self.backend, self.admin, {"email": "member@example.com"})["users"][0]
        self.assertEqual(found["user_id"], MEMBER)
        self.assertTrue(found["email_verified"])
        self.assertFalse(found["premium_access"]["granted"])
        granted = self.change()
        self.assertTrue(granted["premium_access"]["granted"])
        require_premium_access(self.backend, MEMBER)
        self.assertEqual(self.ddb.accounts[MEMBER]["paid_credits_available"], 0)
        self.assertNotIn("paid_membership_status", self.ddb.accounts[MEMBER])
        self.assertEqual(self.ddb.accounts[MEMBER]["free_available_bytes"], self.backend.cfg.free_lifetime_bytes)
        revoked = self.change(False)
        self.assertFalse(revoked["premium_access"]["granted"])
        self.assert_api_error("premium_access_required", require_premium_access, self.backend, MEMBER)
        self.assertEqual([a["action"] for a in self.ddb.admin_audits.values()], ["premium_access_granted", "premium_access_revoked"])
        for event in self.ddb.admin_audits.values():
            self.assertEqual(event["actor_sub"], OWNER)
            self.assertEqual(event["target_sub"], MEMBER)
            self.assertEqual(event["reason"], "Premium pilot access")

    def test_admin_requires_pinned_subject_and_group_for_reads_and_writes(self):
        for claims in (self.claims(OWNER), {**self.claims(MEMBER), "cognito:groups": ["strokesense-admin"]},
                       {**self.admin, "token_use": "id"}):
            with self.subTest(claims=claims):
                self.assert_api_error("admin_forbidden", lookup_premium_user, self.backend, claims, {"email": "member@example.com"})
                self.assert_api_error("admin_forbidden", change_premium_access, self.backend, claims, MEMBER,
                                      {"enabled": True, "reason": "Attempted elevation"})
        self.assertEqual(self.cognito.list_calls, [])
        self.assertEqual(self.ddb.accounts, {})

    def test_disabled_unverified_or_mismatched_actor_cannot_read_grant_or_revoke(self):
        self.change()
        before = copy.deepcopy(self.ddb.accounts[MEMBER])
        initial_actor = copy.deepcopy(self.cognito.users[self.owner_username])
        for scenario in ("disabled", "unverified", "mismatched", "missing_username"):
            with self.subTest(scenario=scenario):
                self.cognito.users[self.owner_username] = copy.deepcopy(initial_actor)
                claims = dict(self.admin)
                if scenario == "disabled":
                    self.cognito.users[self.owner_username]["Enabled"] = False
                elif scenario == "unverified":
                    self.cognito.users[self.owner_username]["UserAttributes"][2]["Value"] = "false"
                elif scenario == "mismatched":
                    claims["username"] = self.member_username
                else:
                    del claims["username"]
                self.cognito.list_calls.clear()
                code = "unauthorized" if scenario == "missing_username" else "premium_identity_unverified"
                self.assert_api_error(code, lookup_premium_user, self.backend, claims, {"email": "member@example.com"})
                for enabled in (True, False):
                    self.assert_api_error(code, change_premium_access, self.backend, claims, MEMBER,
                                          {"enabled": enabled, "reason": "Direct API request"})
                self.assertEqual(self.cognito.list_calls, [], "Actor must be checked before searching target identities")
                self.assertEqual(self.ddb.accounts[MEMBER], before)
                self.assertEqual(len(self.ddb.admin_audits), 1)

    def test_actor_identity_outage_fails_closed_without_target_reads_or_writes(self):
        for error in (FakeAwsError("UserNotFoundException"), FakeAwsError("TooManyRequestsException")):
            code = "premium_identity_unverified" if error.response["Error"]["Code"] == "UserNotFoundException" else "premium_identity_unavailable"
            with self.subTest(code=code), patch.object(self.cognito, "admin_get_user", side_effect=error):
                self.assert_api_error(code, lookup_premium_user, self.backend, self.admin, {"email": "member@example.com"})
                self.assert_api_error(code, self.change)
                self.assert_api_error(code, self.change, False)
        self.assertEqual(self.cognito.list_calls, [])
        self.assertEqual(self.ddb.accounts, {})
        self.assertEqual(self.ddb.admin_audits, {})

    def test_owner_cannot_be_revoked_via_panel_and_prior_denial_wins(self):
        self.assert_api_error("premium_owner_protected", self.change, False, OWNER)
        self.backend._account(OWNER)
        self.ddb.accounts[OWNER]["premium_access_granted"] = False
        self.assertFalse(account_access(self.backend, self.admin)["premium_access"]["granted"])
        self.assertEqual(self.ddb.admin_audits, {})

    def test_fresh_lookup_rejects_disabled_unverified_or_replaced_identity(self):
        self.cognito.list_snapshot = copy.deepcopy(self.cognito.users)
        for mutation in ("disabled", "unverified", "email", "subject"):
            with self.subTest(mutation=mutation):
                self.cognito.users = copy.deepcopy(self.cognito.list_snapshot)
                user = self.cognito.users[self.member_username]
                if mutation == "disabled":
                    user["Enabled"] = False
                elif mutation == "unverified":
                    user["UserAttributes"][2]["Value"] = "false"
                elif mutation == "email":
                    user["UserAttributes"][1]["Value"] = "changed@example.com"
                else:
                    user["UserAttributes"][0]["Value"] = OTHER
                if mutation != "subject":
                    self.assert_api_error("premium_user_not_found", lookup_premium_user, self.backend, self.admin, {"email": "member@example.com"})
                if mutation != "email":
                    self.assert_api_error("premium_user_not_found", self.change)
        self.assertEqual(self.ddb.admin_audits, {})

    def test_search_checks_all_pages_and_refuses_ambiguous_email(self):
        self.cognito.pages = [
            {"Users": [{"Username": self.member_username}], "PaginationToken": "1"},
            {"Users": [{"Username": self.other_username}]},
        ]
        self.assert_api_error("premium_identity_ambiguous", lookup_premium_user, self.backend, self.admin, {"email": "member@example.com"})
        self.assertEqual(len(self.cognito.list_calls), 2)
        self.assertEqual([call["Username"] for call in self.cognito.get_calls], [self.owner_username])
        self.cognito.pages = [{"Users": [], "PaginationToken": "1"}, {"Users": [{"Username": self.member_username}]}]
        found = lookup_premium_user(self.backend, self.admin, {"email": "member@example.com"})
        self.assertEqual(found["users"][0]["user_id"], MEMBER)
        self.assertEqual(self.cognito.get_calls[-1]["Username"], self.member_username)

    def test_malformed_and_nonexistent_identity_cannot_be_granted(self):
        for value in ("", "__strokesense_cpu_admissions__/today", "member@example.com", "../users", None):
            self.assert_api_error("invalid_premium_user", self.change, True, value)
        self.assert_api_error("premium_user_not_found", self.change, True, MISSING)
        self.assertEqual(lookup_premium_user(self.backend, self.admin, {"email": "missing@example.com"}), {"users": []})
        for email in ('member@example.com" or sub ^= "', "member@example.com\n", "", None):
            if isinstance(email, str) and email.endswith("\n"):
                email = "member\n@example.com"
            self.assert_api_error("invalid_email", lookup_premium_user, self.backend, self.admin, {"email": email})
        for body in (
            {"enabled": "true", "reason": "invalid type"}, {"enabled": 1, "reason": "invalid type"},
            {"enabled": True, "reason": " "}, {"enabled": True, "reason": "x" * 501},
            {"enabled": True, "reason": "hidden\u200btext"},
            {"enabled": True, "reason": "Forged owner", "email": "kemalgcortuk@gmail.com"},
        ):
            self.assert_api_error("invalid_premium_access", change_premium_access, self.backend, self.admin, MEMBER, body)
        self.assertEqual(self.ddb.admin_audits, {})

    def test_failed_audit_rolls_back_grant_and_owner_bootstrap(self):
        self.ddb.fail_audit = True
        self.assert_api_error("audit_unavailable", self.change)
        self.assertNotIn("premium_access_granted", self.ddb.accounts[MEMBER])
        self.assert_api_error("audit_unavailable", account_access, self.backend, self.admin)
        self.assertNotIn("premium_access_granted", self.ddb.accounts[OWNER])
        self.assertEqual(self.ddb.admin_audits, {})

    def test_concurrent_admin_change_fails_instead_of_overwriting(self):
        self.change()
        def concurrent_revoke():
            self.ddb.accounts[MEMBER].update(premium_access_granted=False, premium_access_version="concurrent-version")
        self.ddb.before_transaction = concurrent_revoke
        self.assert_api_error("premium_access_conflict", self.change)
        self.assertFalse(self.ddb.accounts[MEMBER]["premium_access_granted"])
        self.assertEqual(len(self.ddb.admin_audits), 1)

    def test_owner_bootstrap_does_not_overwrite_concurrent_explicit_denial(self):
        def concurrent_denial():
            self.ddb.accounts[OWNER]["premium_access_granted"] = False
        self.ddb.before_transaction = concurrent_denial
        self.assertFalse(account_access(self.backend, self.admin)["premium_access"]["granted"])
        self.assertEqual(self.ddb.admin_audits, {})

    def test_grant_never_bypasses_runtime_or_legacy_allowance(self):
        self.change()
        self.assert_api_error("billing_not_configured", self.backend.start_upload, MEMBER,
                              {"tier": "premium", "size_bytes": 1000, "content_type": "video/mp4"})
        for field in ("paid_billing_enabled", "paid_gpu_enabled", "gpu_dispatch_ready"):
            object.__setattr__(self.backend.cfg, field, True)
        self.assertFalse(account_access(self.backend, self.claims(MEMBER))["premium_access"]["available"])
        self.assert_api_error("paid_membership_required", self.backend.start_upload, MEMBER,
                              {"tier": "premium", "size_bytes": 1000, "content_type": "video/mp4"})
        self.assertEqual(self.ddb.jobs, {})

    def test_revocation_blocks_legacy_allowance_and_atomic_reservation_race(self):
        self.change()
        self.ddb.accounts[MEMBER].update(
            paid_membership_status="active", paid_membership_expires_at=self.now + 3600,
            paid_credits_available=1,
        )
        evaluate_paid_membership(self.ddb.accounts[MEMBER], self.now)
        self.change(False)
        self.assert_api_error("premium_access_required", evaluate_paid_membership, self.ddb.accounts[MEMBER], self.now)
        record = {"job_id": "a" * 32, "user_id": MEMBER, "tier": "paid", "size_bytes": 1000, "status": "uploading"}
        with self.assertRaises(Exception) as blocked:
            self.backend._quota_transaction(record, "reserve")
        self.assertTrue(_is_conditional(blocked.exception))
        self.assertEqual(self.ddb.accounts[MEMBER]["paid_credits_available"], 1)
        self.assertEqual(self.ddb.jobs, {})

    def test_free_upload_still_works_after_premium_revocation(self):
        self.change(False)
        uploaded = self.backend.start_upload(MEMBER, {"tier": "free", "size_bytes": 1000, "content_type": "video/mp4"})
        self.assertEqual(uploaded["tier"], "free")
        self.assertEqual(self.ddb.accounts[MEMBER]["free_reserved_bytes"], 1000)

    def test_http_routes_use_authorizer_claims_and_cannot_self_grant(self):
        def event(path, method="GET", claims=None, body=None, query=None):
            return {
                "rawPath": path,
                "requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": claims or self.admin}}},
                "body": json.dumps(body) if body is not None else "",
                "queryStringParameters": query,
            }
        with patch("aws_app.handler._build_service", return_value=self.backend):
            me = lambda_handler(event("/me"), None)
            self.assertEqual(me["statusCode"], 200)
            self.assertTrue(json.loads(me["body"])["premium_access"]["granted"])
            denied = lambda_handler(event(f"/admin/users/{MEMBER}/premium", "POST", self.claims(MEMBER),
                                          {"enabled": True, "reason": "I claim admin"}), None)
            self.assertEqual(denied["statusCode"], 403)
            approved = lambda_handler(event(f"/admin/users/{MEMBER}/premium", "POST", body={"enabled": True, "reason": "Invited pilot user"}), None)
            self.assertEqual(approved["statusCode"], 200)
            lookup = lambda_handler(event("/admin/users", query={"email": "member@example.com"}), None)
            self.assertTrue(json.loads(lookup["body"])["users"][0]["premium_access"]["granted"])
            self.assertEqual(approved["headers"]["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
