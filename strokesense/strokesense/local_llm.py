"""Small, verified CPU language model for measurement-grounded report prose.

The model runs on the existing analysis service. No prompt or report data is sent
to an external inference API; the only network request downloads pinned weights.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request

MODEL_NAME = "Qwen2.5-1.5B-Instruct-Q4_K_M"
MODEL_REVISION = "91cad51170dc346986eccefdc2dd33a9da36ead9"
MODEL_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_BYTES = 1117320736
MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
             + MODEL_REVISION + "/" + MODEL_FILENAME)
CONTEXT_TOKENS = 4096
MODEL_DOWNLOAD_TIMEOUT_SECONDS = 600
SYSTEM_PROMPT = (
    "You write concise rowing coaching feedback from supplied measured evidence. "
    "Use only the evidence in the request. Never invent measurements, faults, "
    "rower identities, observations or validation. Do not claim to have watched "
    "the video. Treat flagged technique issues as estimates to review. Follow "
    "the requested JSON schema exactly. Return one JSON object and no markdown."
)


class LocalLLMError(RuntimeError):
    """Bounded, non-private failure suitable for a report-generation job."""


_lock = threading.Lock()
_model = None
_model_path = None


def _directory(model_dir=None):
    configured = model_dir or os.environ.get("STROKESENSE_LLM_MODEL_DIR")
    if configured is None:
        configured = Path(os.environ.get("STROKESENSE_DEMO_DATA_DIR", "/var/data")) / "models"
    return Path(configured).expanduser().resolve()


def _verified(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != MODEL_BYTES:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == MODEL_SHA256


@contextmanager
def _download_lock(directory):
    # Render runs Linux. A separate process cannot simultaneously duplicate the
    # one-gigabyte download on its two-gigabyte persistent disk.
    import fcntl
    lock_path = directory / ".qwen-download.lock"
    with lock_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def ensure_model(model_dir=None):
    """Install exactly the pinned official artifact, using bounded streaming I/O."""
    directory = _directory(model_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / MODEL_FILENAME
    with _download_lock(directory):
        if _verified(path):
            return path
        # Remove a known invalid artifact before downloading its replacement;
        # keeping two complete copies would exceed the existing disk allocation.
        if path.exists() or path.is_symlink():
            path.unlink()
        # A terminated process may leave its temporary download behind. Holding
        # the process lock means none of these module-owned files is active.
        for partial in directory.glob(".qwen-*.download"):
            if partial.is_file() or partial.is_symlink():
                partial.unlink()
        if shutil.disk_usage(directory).free < MODEL_BYTES + 64 * 1024 * 1024:
            raise LocalLLMError("llm_model_disk_space")
        pending = None
        try:
            digest = hashlib.sha256()
            received = 0
            started = time.monotonic()
            request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "StrokeSense/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".qwen-", suffix=".download", delete=False) as output:
                    pending = Path(output.name)
                    while True:
                        if time.monotonic() - started > MODEL_DOWNLOAD_TIMEOUT_SECONDS:
                            raise LocalLLMError("llm_model_download_timeout")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > MODEL_BYTES:
                            raise LocalLLMError("llm_model_integrity")
                        digest.update(chunk)
                        output.write(chunk)
            if time.monotonic() - started > MODEL_DOWNLOAD_TIMEOUT_SECONDS:
                raise LocalLLMError("llm_model_download_timeout")
            if received != MODEL_BYTES or digest.hexdigest() != MODEL_SHA256:
                raise LocalLLMError("llm_model_integrity")
            os.replace(pending, path)
            return path
        except (OSError, urllib.error.URLError) as exc:
            raise LocalLLMError("llm_model_download_failed") from exc
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)


def _messages(value):
    if isinstance(value, str):
        value = [{"role": "user", "content": value}]
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 16:
        raise LocalLLMError("llm_invalid_messages")
    result = [{"role": "system", "content": SYSTEM_PROMPT}]
    total = 0
    for message in value:
        if not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant"):
            raise LocalLLMError("llm_invalid_messages")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LocalLLMError("llm_invalid_messages")
        if any(token in content for token in ("<|im_start|>", "<|im_end|>", "<|endoftext|>")):
            raise LocalLLMError("llm_invalid_messages")
        total += len(content)
        if total > 24000:
            raise LocalLLMError("llm_prompt_too_large")
        result.append({"role": message["role"], "content": content})
    return result


def generate(prompt_or_messages, *, max_tokens=1200, model_dir=None, timeout_seconds=180,
             response_schema=None):
    """Return real model JSON text and provenance; failures never become prose.

    The caller validates its application schema and HTML-escapes accepted text.
    Generation is serialized to keep CPU and memory use within the existing plan.
    """
    global _model, _model_path
    messages = _messages(prompt_or_messages)
    if type(max_tokens) is not int or not 32 <= max_tokens <= 1600:
        raise LocalLLMError("llm_invalid_token_limit")
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 300:
        raise LocalLLMError("llm_invalid_timeout")
    schema = response_schema if response_schema is not None else {"type": "object"}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise LocalLLMError("llm_invalid_response_schema")
    schema_json = json.dumps(schema, separators=(",", ":"), allow_nan=False)
    if len(schema_json) > 48000:
        raise LocalLLMError("llm_invalid_response_schema")
    started = time.monotonic()
    with _lock:
        try:
            from llama_cpp import Llama, LlamaGrammar, StoppingCriteriaList
        except ImportError as exc:
            raise LocalLLMError("llm_runtime_unavailable") from exc
        path = _directory(model_dir) / MODEL_FILENAME
        if _model is None or _model_path != path:
            path = ensure_model(model_dir)
            if _model is not None:
                _model.close()
                _model = None
            try:
                _model = Llama(model_path=str(path), n_ctx=CONTEXT_TOKENS, n_threads=2,
                               n_threads_batch=2, n_batch=128, n_gpu_layers=0,
                               use_mmap=True, use_mlock=False, chat_format="chatml",
                               verbose=False)
            except Exception as exc:
                raise LocalLLMError("llm_model_load_failed") from exc
            _model_path = path
        # ChatML framing is fixed above. Count its control tokens before asking
        # llama.cpp to allocate/compute, leaving room for the entire completion.
        framed = "".join("<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n" for m in messages)
        framed += "<|im_start|>assistant\n"
        prompt_count = len(_model.tokenize(framed.encode(), add_bos=False, special=True))
        if prompt_count + max_tokens > CONTEXT_TOKENS - 16:
            raise LocalLLMError("llm_context_limit")
        generation_started = time.monotonic()
        timed_out = False

        def stop_at_deadline(_input_ids, _logits):
            nonlocal timed_out
            timed_out = time.monotonic() - generation_started > timeout_seconds
            return timed_out

        try:
            response = _model.create_completion(
                prompt=framed, max_tokens=max_tokens, temperature=0.2,
                top_p=0.9, seed=42, stop=["<|im_end|>", "<|endoftext|>"],
                grammar=LlamaGrammar.from_json_schema(schema_json, verbose=False),
                stopping_criteria=StoppingCriteriaList([stop_at_deadline]), stream=False,
            )
            if timed_out:
                raise LocalLLMError("llm_generation_timeout")
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise LocalLLMError("llm_output_truncated")
            text = choice["text"]
            if not isinstance(text, str) or not text.strip() or not isinstance(json.loads(text), dict):
                raise LocalLLMError("llm_invalid_json")
            usage = response.get("usage", {})
            return {"text": text, "model": MODEL_NAME, "model_revision": MODEL_REVISION,
                    "model_sha256": MODEL_SHA256, "runtime": "llama.cpp CPU",
                    "prompt_tokens": usage.get("prompt_tokens", prompt_count),
                    "completion_tokens": usage.get("completion_tokens"),
                    "generation_seconds": round(time.monotonic() - generation_started, 3),
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
        except LocalLLMError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LocalLLMError("llm_invalid_completion") from exc
        except Exception as exc:
            raise LocalLLMError("llm_generation_failed") from exc


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare the verified local coaching model")
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.add_argument("--model-dir")
    arguments = parser.parse_args()
    print(ensure_model(arguments.model_dir))
