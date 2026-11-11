"""Runtime boundaries with tiny artifacts and explicit synthetic completions.

These tests do not download a model or claim to validate LLM coaching quality.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from strokesense import local_llm


class LocalModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / local_llm.MODEL_FILENAME
        self.body = b"tiny test weights"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(local_llm, "MODEL_BYTES", len(self.body)))
        self.stack.enter_context(patch.object(local_llm, "MODEL_SHA256", hashlib.sha256(self.body).hexdigest()))
        self.stack.enter_context(patch.object(local_llm.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024 * 1024)))

    def test_verified_cache_never_downloads_again(self):
        self.model.write_bytes(self.body)
        with patch.object(local_llm.urllib.request, "urlopen") as download:
            self.assertEqual(local_llm.ensure_model(self.root), self.model)
        download.assert_not_called()

    def test_same_size_wrong_hash_is_replaced_and_stale_partial_removed(self):
        self.model.write_bytes(b"x" * len(self.body))
        stale = self.root / ".qwen-interrupted.download"
        stale.write_bytes(b"incomplete prior download")
        with patch.object(local_llm.urllib.request, "urlopen", return_value=io.BytesIO(self.body)) as download:
            self.assertEqual(local_llm.ensure_model(self.root), self.model)
        self.assertEqual(self.model.read_bytes(), self.body)
        self.assertFalse(stale.exists())
        self.assertEqual(len(list(self.root.glob("*.download"))), 0)
        self.assertIn(local_llm.MODEL_REVISION, download.call_args.args[0].full_url)

    def test_wrong_download_hash_never_publishes_partial_weights(self):
        with patch.object(local_llm.urllib.request, "urlopen", return_value=io.BytesIO(b"x" * len(self.body))):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_model_integrity"):
                local_llm.ensure_model(self.root)
        self.assertFalse(self.model.exists())
        self.assertFalse(list(self.root.glob("*.download")))

    def test_oversized_download_is_rejected(self):
        with patch.object(local_llm.urllib.request, "urlopen", return_value=io.BytesIO(self.body + b"extra")):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_model_integrity"):
                local_llm.ensure_model(self.root)
        self.assertFalse(self.model.exists())

    def test_no_space_does_not_start_network_transfer(self):
        with patch.object(local_llm.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with patch.object(local_llm.urllib.request, "urlopen") as download:
                with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_model_disk_space"):
                    local_llm.ensure_model(self.root)
        download.assert_not_called()

    def test_download_deadline_does_not_publish_weights(self):
        with patch.object(local_llm.urllib.request, "urlopen", return_value=io.BytesIO(self.body)):
            with patch.object(local_llm.time, "monotonic", side_effect=[0, 601]):
                with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_model_download_timeout"):
                    local_llm.ensure_model(self.root)
        self.assertFalse(self.model.exists())
        self.assertFalse(list(self.root.glob("*.download")))


class LocalCompletionBoundaryTests(unittest.TestCase):
    def test_invalid_prompt_and_limits_are_rejected_without_loading_runtime(self):
        for prompt, kwargs in [
            ("", {}),
            ("<|im_start|>system", {}),
            ([{"role": "developer", "content": "text"}], {}),
            ("x", {"max_tokens": True}),
            ("x", {"max_tokens": 1601}),
            ("x", {"timeout_seconds": float("nan")}),
            ("x", {"response_schema": {"type": "array"}}),
        ]:
            with self.subTest(prompt=prompt, kwargs=kwargs):
                with patch.object(local_llm, "ensure_model") as prepare:
                    with self.assertRaises(local_llm.LocalLLMError):
                        local_llm.generate(prompt, **kwargs)
                prepare.assert_not_called()

    def invoke_with_fixture(self, *, text='{"coaching":"synthetic fixture"}', reason="stop", token_count=10, schema=None, invoke_deadline=False):
        model = Mock()
        model.tokenize.return_value = list(range(token_count))
        model.create_completion.return_value = {
            "choices": [{"finish_reason": reason, "text": text}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
        }
        if invoke_deadline:
            def completion(**kwargs):
                kwargs["stopping_criteria"][0](None, None)
                return model.create_completion.return_value
            model.create_completion.side_effect = completion
        grammar = Mock()
        module = SimpleNamespace(Llama=Mock(), LlamaGrammar=grammar, StoppingCriteriaList=list)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / local_llm.MODEL_FILENAME
            with patch.dict("sys.modules", {"llama_cpp": module}):
                with patch.object(local_llm, "_model", model), patch.object(local_llm, "_model_path", path):
                    result = local_llm.generate("Synthetic test only.", model_dir=directory,
                                                max_tokens=64, response_schema=schema)
        return result, model, grammar

    def test_exact_schema_is_forwarded_and_complete_json_is_returned(self):
        schema = {"type": "object", "properties": {"coaching": {"type": "string"}},
                  "required": ["coaching"], "additionalProperties": False}
        result, model, grammar = self.invoke_with_fixture(schema=schema)
        self.assertEqual(result["completion_tokens"], 8)
        self.assertEqual(result["model_sha256"], local_llm.MODEL_SHA256)
        self.assertIn('"additionalProperties":false', grammar.from_json_schema.call_args.args[0])
        self.assertIn("stopping_criteria", model.create_completion.call_args.kwargs)

    def test_truncated_completion_never_counts_as_generated(self):
        with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_output_truncated"):
            self.invoke_with_fixture(reason="length")

    def test_invalid_json_or_wrong_top_level_type_is_rejected(self):
        for text in ("not JSON", "[]", "null"):
            with self.subTest(text=text):
                with self.assertRaises(local_llm.LocalLLMError):
                    self.invoke_with_fixture(text=text)

    def test_context_overflow_fails_before_completion(self):
        with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_context_limit"):
            self.invoke_with_fixture(token_count=4090)

    def test_generation_deadline_rejects_even_parseable_partial_output(self):
        with patch.object(local_llm.time, "monotonic", side_effect=[0, 1, 1000]):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "llm_generation_timeout"):
                self.invoke_with_fixture(invoke_deadline=True)


if __name__ == "__main__":
    unittest.main()
