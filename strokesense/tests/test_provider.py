"""Offline contract tests for a configurable LLM chat adapter.

Responses, metadata approvals and recording evidence are fictional fixtures.
No test sends HTTP traffic or creates chargeable provider requests.
"""
from __future__ import annotations

import copy
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
    return io.BytesIO(json.dumps({"choices": [
        {"message": {"content": json.dumps(candidate)}}
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

    def test_payload_does_not_send_private_paths_or_reviewers(self):
        snap = copy.deepcopy(self.snapshot)
        snap["private_source_path"] = "/private/sensitive-training-group"
        cues = copy.deepcopy(self.cues)
        cues["fixture-cue"]["reviewed_by"] = "private reviewer name"
        self.assertEqual(snap["snapshot_sha256"], self.snapshot["snapshot_sha256"])
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

    def test_malformed_responses_fail_closed(self):
        from strokesense.provider import ProviderError
        malformed = (
            b"not-json",
            b"{}",
            json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode(),
            json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode(),
            json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode() if False else b"[]",
        )
        for data in malformed:
            with self.subTest(data=data[:20]), patch(
                "strokesense.provider.urlopen", return_value=io.BytesIO(data)
            ), self.assertRaises(ProviderError):
                self.generator()(1, [])

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


if __name__ == "__main__":
    unittest.main()
