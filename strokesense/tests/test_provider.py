"""Offline contract tests for a configurable LLM chat adapter.

Responses, metadata approvals and recording evidence are fictional fixtures.
No test sends HTTP traffic or creates chargeable provider requests.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_validation import trusted_synthetic_fixture


def fake_response(candidate):
    """Fictional *complete* OpenAI-compatible chat response, not a live model."""
    return io.BytesIO(json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(candidate)}}
    ]}).encode("utf-8"))


class ConfiguredProviderTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.candidate, self.cues = trusted_synthetic_fixture()

    def generator(self, **changes):
        from strokesense.provider import OpenAIChatGenerator
        params = dict(evidence_snapshot=self.snapshot, reviewed_cues=self.cues,
                      model="fixture-chat-model", api_key="fixture-token",
                      endpoint="https://example.test/v1/chat/completions",
                      timeout_seconds=7.5)
        params.update(changes)
        return OpenAIChatGenerator(**params)

    def test_constructing_client_does_not_access_network(self):
        with patch("urllib.request.urlopen") as urlopen:
            generator = self.generator()
            self.assertTrue(callable(generator))
            urlopen.assert_not_called()

    def test_request_uses_https_auth_explicit_model_and_timeout(self):
        with patch("strokesense.provider.urlopen", return_value=fake_response(self.candidate)) as open_url:
            self.assertEqual(self.generator()(1, []), self.candidate)
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 7.5)
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-token")
        request_body = json.loads(request.data)
        self.assertEqual(request_body["model"], "fixture-chat-model")
        self.assertEqual(request_body["response_format"], {"type": "json_object"})
        self.assertEqual(request_body["max_completion_tokens"], 512)

    def test_oversize_utf8_prompt_rejected_before_network(self):
        """Rehashed but oversized synthetic evidence must not reach HTTPS."""
        from strokesense.evidence import validate_reference_graph
        from strokesense.provider import ProviderError
        snap = copy.deepcopy(self.snapshot)
        secret = "private_marker_" + ("🛶" * 20000)
        snap["analysis_id"] = secret
        payload = {key: value for key, value in snap.items()
                   if key != "snapshot_sha256"}
        snap["snapshot_sha256"] = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
        self.assertTrue(validate_reference_graph(snap))
        with patch("strokesense.provider.urlopen",
                   return_value=fake_response(self.candidate)) as opened:
            with self.assertRaises(ProviderError) as caught:
                self.generator(evidence_snapshot=snap)(1, [])
        opened.assert_not_called()
        self.assertEqual(str(caught.exception), "provider_prompt_too_large")
        self.assertNotIn("private_marker_", str(caught.exception))

    def test_payload_does_not_send_private_paths_or_reviewers(self):
        snap = copy.deepcopy(self.snapshot)
        snap["private_source_path"] = "/private/sensitive-training-group"
        cues = copy.deepcopy(self.cues)
        cues["fixture-cue"]["reviewed_by"] = "private reviewer name"
        payload = {k: v for k, v in snap.items() if k != "snapshot_sha256"}
        snap["snapshot_sha256"] = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
        with patch("strokesense.provider.urlopen", return_value=fake_response(self.candidate)) as open_url:
            self.generator(evidence_snapshot=snap, reviewed_cues=cues)(1, [])
        payload = open_url.call_args.args[0].data.decode()
        self.assertNotIn("private_source_path", payload)
        self.assertNotIn("/private/sensitive", payload)
        self.assertNotIn("private reviewer name", payload)
        self.assertNotIn("reviewed_by", payload)
        self.assertNotIn("fixture-token", payload)
        self.assertIn(self.candidate["finding_id"], payload)
        self.assertIn("fixture-cue", payload)

    def test_rejects_missing_settings_and_insecure_endpoints(self):
        from strokesense.provider import OpenAIChatGenerator, ProviderError
        for endpoint in ("http://example.test/v1/chat/completions",
                         "https://user:password@example.test/v1/chat/completions",
                         "https://example.test/v1/chat/completions?key=secret",
                         "https://example.test/v1/chat/completions#fragment",
                         "ftp://example.test/", "https:///missing-host"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.generator(endpoint=endpoint)
        for bad in (0, -1, 100, float("nan"), True):
            with self.subTest(timeout=bad), self.assertRaises(ValueError):
                self.generator(timeout_seconds=bad)
        with self.assertRaises(ProviderError):
            self.generator(api_key="")
        with self.assertRaises(ProviderError):
            self.generator(model="")
        with patch.dict(os.environ, {"STROKESENSE_LLM_API_KEY": "",
                                      "STROKESENSE_LLM_MODEL": ""}):
            with self.assertRaises(ProviderError):
                OpenAIChatGenerator.from_env(self.snapshot, self.cues)

    def test_missing_independent_approval_blocks_network(self):
        from strokesense.provider import ProviderError
        with patch("strokesense.provider.urlopen") as open_url:
            with self.assertRaises(ProviderError):
                self.generator(reviewed_cues={})(1, [])
            with self.assertRaises(ProviderError):
                self.generator(evidence_snapshot={"schema_version": 1})(1, [])
        open_url.assert_not_called()

    def test_malformed_reviewed_fault_lists_are_rejected_before_http(self):
        """Synthetic reviewer claims are not approval for malformed cue codes."""
        from strokesense.provider import ProviderError
        malformed = (
            "early_arms", ("early_arms",), {"early_arms"},
            {"early_arms": True}, None, [],
            ["early_arms", "early_arms"],
            ["early_arms", "unknown_fault"],
            ["early_arms", 42],
        )
        for codes in malformed:
            with self.subTest(codes=repr(codes)):
                cues = copy.deepcopy(self.cues)
                cues["fixture-cue"]["fault_codes"] = codes
                with patch("strokesense.provider.urlopen") as opened:
                    with self.assertRaises(ProviderError) as caught:
                        self.generator(reviewed_cues=cues)(1, [])
                self.assertEqual(str(caught.exception), "no_approved_cues")
                opened.assert_not_called()

    def test_valid_reviewed_cue_isolated_from_malformed_catalogue_entry(self):
        """Only schema-valid, independently reviewed cue IDs reach the model."""
        cues = copy.deepcopy(self.cues)
        cues["fixture-malformed-cue"] = {
            "review_status": "approved",
            "reviewed_by": "fictional synthetic reviewer",
            "fault_codes": ["early_arms", "early_arms"],
        }
        with patch("strokesense.provider.urlopen",
                   return_value=fake_response(self.candidate)) as opened:
            self.assertEqual(self.generator(reviewed_cues=cues)(1, []),
                             self.candidate)
        body = json.loads(opened.call_args.args[0].data)
        data = json.loads(body["messages"][1]["content"])
        self.assertEqual(data["approved_cues"],
                         {"fixture-cue": {"fault_codes": ["early_arms"]}})
        self.assertNotIn("fictional synthetic reviewer", opened.call_args.args[0].data.decode())

    def test_network_error_is_sanitized_and_withheld_by_correction(self):
        from strokesense import correction
        from strokesense.provider import ProviderError
        with patch("strokesense.provider.urlopen",
                   side_effect=URLError("sensitive bearer private log data")):
            with self.assertRaises(ProviderError) as caught:
                self.generator()(1, [])
            self.assertNotIn("sensitive", str(caught.exception))
            answer = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues)
        self.assertEqual(answer["status"], "withheld")
        self.assertEqual(answer["attempts"], 1)
        self.assertEqual(answer["errors"], ["generation_failed"])
        self.assertNotIn("sensitive", json.dumps(answer))

    def test_duplicate_json_fields_are_not_interpreted_as_valid_answers(self):
        """Ambiguous object names must fail even when the last copy looks valid."""
        from strokesense.provider import ProviderError
        valid = json.dumps(self.candidate)
        choice = [{"finish_reason": "stop", "message": {"content": valid}}]
        candidate_duplicate = (valid[:-1] + ', "finding_id": ' +
                               json.dumps(self.candidate["finding_id"]) + "}")
        replies = (
            '{"choices":[],"choices":' + json.dumps(choice) + '}',
            json.dumps({"choices": [
                {"finish_reason": "stop",
                 "message": {"content": candidate_duplicate}}
            ]}),
            '{"choices": [{"finish_reason": "stop", "message": {' +
            '"content": ' + json.dumps(valid) + ', "content": ' +
            json.dumps(valid) + '}}]}',
        )
        for reply in replies:
            with self.subTest(reply=reply[:75]), patch(
                "strokesense.provider.urlopen",
                return_value=io.BytesIO(reply.encode("utf-8")),
            ):
                with self.assertRaises(ProviderError) as caught:
                    self.generator()(1, [])
                self.assertEqual(str(caught.exception), "invalid_provider_response")

    def test_non_json_or_overflowed_numeric_constants_are_refused(self):
        """Python's permissive JSON parser must not accept NaN/Inf or 1e999."""
        from strokesense.provider import ProviderError
        valid = json.dumps(self.candidate)
        choice = json.dumps([
            {"finish_reason": "stop", "message": {"content": valid}}
        ])
        replies = [
            '{"choices": ' + choice + ', "ignored": ' + constant + '}'
            for constant in ("NaN", "Infinity", "-Infinity", "1e999")
        ]
        replies.append(json.dumps({"choices": [
            {"finish_reason": "stop", "message": {
                "content": valid[:-1] + ', "ignored": NaN}',
            }}
        ]}))
        for reply in replies:
            with self.subTest(reply=reply[-30:]), patch(
                "strokesense.provider.urlopen",
                return_value=io.BytesIO(reply.encode("utf-8")),
            ):
                with self.assertRaises(ProviderError) as caught:
                    self.generator()(1, [])
                self.assertEqual(str(caught.exception), "invalid_provider_response")

    def test_ambiguous_json_withheld_without_retry_or_candidate_leak(self):
        from strokesense import correction
        valid = json.dumps(self.candidate)
        duplicate = valid[:-1] + ', "finding_id": ' + json.dumps(
            self.candidate["finding_id"]) + '}'
        envelope = json.dumps({"choices": [{
            "finish_reason": "stop", "message": {"content": duplicate},
        }]})
        with patch("strokesense.provider.urlopen",
                   return_value=io.BytesIO(envelope.encode("utf-8"))) as opened:
            result = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues,
            )
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 1)
        self.assertIsNone(result["released"])
        self.assertEqual(result["errors"], ["generation_failed"])
        self.assertNotIn(self.candidate["explanation"], json.dumps(result))


    def test_explicit_refusals_and_tool_calls_cannot_release_coaching(self):
        from strokesense.provider import ProviderError
        candidate = json.dumps(self.candidate)
        variants = (
            {"role": "tool", "content": candidate},
            {"role": None, "content": candidate},
            {"role": "assistant", "content": candidate,
             "refusal": "PRIVATE SYNTHETIC REFUSAL CONTENT"},
            {"role": "assistant", "content": candidate,
             "refusal": ""},
            {"role": "assistant", "content": candidate,
             "tool_calls": [{"id": "fictional-call", "type": "function"}]},
            {"role": "assistant", "content": candidate,
             "tool_calls": "invalid-not-an-array"},
            {"role": "assistant", "content": candidate,
             "function_call": {"name": "fictional-tool"}},
        )
        for message in variants:
            raw = json.dumps({"choices": [{
                "finish_reason": "stop", "message": message,
            }]}).encode("utf-8")
            with self.subTest(message=str(message)[:95]), patch(
                "strokesense.provider.urlopen",
                return_value=io.BytesIO(raw),
            ):
                with self.assertRaises(ProviderError) as caught:
                    self.generator()(1, [])
                self.assertEqual(str(caught.exception), "invalid_provider_response")
                self.assertNotIn("PRIVATE SYNTHETIC", str(caught.exception))

        # A finished, ordinary assistant response must remain compatible.
        valid = {"role": "assistant", "content": candidate,
                 "refusal": None, "tool_calls": [], "function_call": None}
        raw = json.dumps({"choices": [{
            "finish_reason": "stop", "message": valid,
        }]}).encode("utf-8")
        with patch("strokesense.provider.urlopen", return_value=io.BytesIO(raw)):
            self.assertEqual(self.generator()(1, []), self.candidate)

    def test_refusal_does_not_trigger_correction_retry_or_leak_text(self):
        from strokesense import correction
        raw = json.dumps({"choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": json.dumps(self.candidate),
                "refusal": "PRIVATE FICTIONAL PROVIDER REFUSAL",
            },
        }]}).encode("utf-8")
        with patch("strokesense.provider.urlopen",
                   return_value=io.BytesIO(raw)) as opened:
            result = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues,
            )
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 1)
        self.assertIsNone(result["released"])
        self.assertEqual(result["errors"], ["generation_failed"])
        self.assertNotIn("PRIVATE FICTIONAL", json.dumps(result))
        self.assertNotIn(self.candidate["explanation"], json.dumps(result))


    def test_malformed_responses_fail_closed(self):
        from strokesense.provider import ProviderError
        malformed = (
            b"not-json",
            b"{}",
            json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode(),
            json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode(),
            b"[]",
        )
        for data in malformed:
            with self.subTest(data=data[:20]), patch(
                "strokesense.provider.urlopen", return_value=io.BytesIO(data)
            ), self.assertRaises(ProviderError):
                self.generator()(1, [])

    def test_provider_refuses_incomplete_filtered_or_unclassified_completion(self):
        """A valid-looking JSON candidate is unsafe without completed generation."""
        from strokesense.provider import ProviderError
        for reason in ("length", "content_filter", "tool_calls", None, "unknown"):
            with self.subTest(finish_reason=reason):
                response = {"choices": [{
                    "finish_reason": reason,
                    "message": {"content": json.dumps(self.candidate)},
                }]}
                with patch("strokesense.provider.urlopen",
                           return_value=io.BytesIO(json.dumps(response).encode())):
                    with self.assertRaises(ProviderError) as caught:
                        self.generator()(1, [])
                self.assertEqual(str(caught.exception), "invalid_provider_response")

        # Missing completion state must not be interpreted as success.
        response = {"choices": [
            {"message": {"content": json.dumps(self.candidate)}}
        ]}
        with patch("strokesense.provider.urlopen",
                   return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaises(ProviderError):
                self.generator()(1, [])

    def test_incomplete_provider_output_withheld_without_retry_or_text(self):
        from strokesense import correction
        candidate = copy.deepcopy(self.candidate)
        candidate["explanation"] = "SYNTHETIC_UNSAFE_INCOMPLETE_ADVICE"
        response = {"choices": [{
            "finish_reason": "length",
            "message": {"content": json.dumps(candidate)},
        }]}
        with patch("strokesense.provider.urlopen",
                   return_value=io.BytesIO(json.dumps(response).encode())) as opened:
            result = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues)
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["errors"], ["generation_failed"])
        self.assertIsNone(result["released"])
        self.assertEqual(opened.call_count, 1)
        self.assertNotIn(candidate["explanation"], json.dumps(result))

    def test_oversize_payload_is_rejected_without_exposing_body(self):
        from strokesense.provider import ProviderError
        with patch("strokesense.provider.urlopen",
                   return_value=io.BytesIO(b"SECRET:" + b"x" * 200000)):
            with self.assertRaises(ProviderError) as caught:
                self.generator()(1, [])
        self.assertNotIn("SECRET", str(caught.exception))

    def test_corrected_model_candidate_released_only_after_validation(self):
        from strokesense import correction
        invalid = copy.deepcopy(self.candidate)
        invalid["observed_count"] = 100
        with patch("strokesense.provider.urlopen",
                   side_effect=[fake_response(invalid), fake_response(self.candidate)]) as open_url:
            result = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues)
        self.assertEqual(result["status"], "released")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["released"], self.candidate)
        second_request = json.loads(open_url.call_args_list[1].args[0].data)
        second_input = json.loads(second_request["messages"][1]["content"])
        self.assertEqual(second_input["prior_error_codes"], ["incorrect_quantity"])
        self.assertEqual(second_input["attempt"], 2)

    def test_persistent_invalid_provider_output_never_releases(self):
        from strokesense import correction
        invalid = copy.deepcopy(self.candidate)
        invalid["stroke_ids"] = ["fabricated-stroke"]
        with patch("strokesense.provider.urlopen",
                   side_effect=[fake_response(invalid) for _ in range(3)]) as open_url:
            result = correction.run_correction(
                self.generator(), evidence_snapshot=self.snapshot,
                reviewed_cues=self.cues)
        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(open_url.call_count, 3)
        self.assertIsNone(result["released"])
        self.assertNotIn(invalid["explanation"], json.dumps(result))


    def test_authorization_is_never_forwarded_to_redirect_targets(self):
        """Redirects must be rejected before urllib replays a bearer token."""
        from urllib.request import Request
        from strokesense import provider
        handler = provider._NoRedirectHandler()
        original = Request("https://example.test/v1/chat/completions",
                           headers={"Authorization": "Bearer fixture-token"})
        with self.assertRaises(HTTPError):
            handler.redirect_request(
                original, None, 302, "Found", {},
                "https://unexpected-host.example.test/collect")
        opener = provider.urlopen.__self__
        self.assertTrue(any(isinstance(h, provider._NoRedirectHandler)
                            for h in opener.handlers))

if __name__ == "__main__":
    unittest.main()
