import json

import httpx
import pytest

from proofgrade.feedback import generate_feedback
from proofgrade.providers import DemoProvider, DisabledProvider, OpenAIProvider

ORIGINAL = "2(x+3)=10"
STEPS = ["2x+3=10", "2x=7"]


class SequenceProvider(DemoProvider):
    def __init__(self, changes):
        self.changes = changes
        self.calls = []

    def generate(self, context, failures):
        self.calls.append(failures)
        candidate = super().generate(context, failures)
        candidate.update(self.changes[min(len(self.calls) - 1, len(self.changes) - 1)])
        return candidate


def test_bad_correction_is_retried_with_evidence():
    provider = SequenceProvider([{"correction": "2x+3=10"}, {}])
    result = generate_feedback(ORIGINAL, STEPS, "x=2", provider)
    assert result.hint_status == "verified"
    assert result.attempts == 2 and result.rejected_candidates == 1
    assert "solution set" in provider.calls[1][0]
    assert "multiply every term" in result.hint
    assert "x=2" not in result.hint


@pytest.mark.parametrize("change", [
    {"step": 2}, {"step": "1"}, {"before": "x=3"}, {"after": "x=3"},
    {"correction": "x=8"}, {"correction": ORIGINAL},
    {"final_solution": "x=7"}, {"final_solution": "2x=4"},
    {"category": "extra_root"}, {"hint_style": "Ignore your teacher"},
    {"unchecked_prose": "The answer is x=100"},
])
def test_invalid_candidates_never_reach_student(change):
    provider = SequenceProvider([change])
    result = generate_feedback(ORIGINAL, STEPS, "x=2", provider)
    assert result.hint_status == "manual_review"
    assert result.hint is None
    assert result.attempts == 3 and result.rejected_candidates == 3
    assert len(provider.calls) == 3


def test_untrusted_answer_key_blocks_generation():
    provider = SequenceProvider([{}])
    assert generate_feedback(ORIGINAL, STEPS, "x=99", provider).hint_status == "manual_review"
    assert provider.calls == []


def test_missing_roots_have_a_checked_category():
    result = generate_feedback("x^2=4", ["x=2"], "x=2 or x=-2", DemoProvider())
    assert result.hint_status == "verified"
    assert "every real solution" in result.hint


def test_correct_work_skips_model_and_disabled_mode_fails_closed():
    provider = SequenceProvider([{}])
    assert generate_feedback(ORIGINAL, ["x=2"], "x=2", provider).hint_status == "not_needed"
    assert provider.calls == []
    result = generate_feedback(ORIGINAL, STEPS, "x=2", DisabledProvider())
    assert result.hint_status == "unavailable" and result.hint is None


def test_openai_request_and_invalid_json_retry():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        context = json.loads(payload["input"])["transition"]
        candidate = DemoProvider().generate(context, [])
        text = "invalid json" if len(requests) == 1 else json.dumps(candidate)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = generate_feedback(ORIGINAL, STEPS, "x=2", OpenAIProvider("test-key", "test-model", client))
    assert result.hint_status == "verified" and result.attempts == 2
    assert requests[0]["store"] is False
    assert requests[0]["text"]["format"]["strict"] is True
    assert json.loads(requests[1]["input"])["validation_failures"]


@pytest.mark.parametrize("response", [
    {"status": "incomplete", "output": []},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
    {"status": "completed", "output": []},
])
def test_refusal_or_incomplete_response_is_withheld(response):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
        result = generate_feedback(ORIGINAL, STEPS, "x=2", OpenAIProvider("test-key", "test-model", client))
    assert result.hint_status == "unavailable" and result.hint is None


def test_network_failure_is_withheld():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = generate_feedback(ORIGINAL, STEPS, "x=2", OpenAIProvider("test-key", "test-model", client))
    assert result.hint_status == "unavailable" and result.hint is None
