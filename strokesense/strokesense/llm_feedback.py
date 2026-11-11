"""Grounded LLM coaching layered onto an existing measured rowing report.

Only allowlisted, compact measurements reach the model. The original metrics,
images and charts remain authoritative; LLM prose adds no numerical claims.
The sidecar binds an actual generation result to both inputs and final HTML.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Mapping

SCHEMA_VERSION = "llm-feedback-v1"
SIDECAR_NAME = "llm-feedback.json"
MEASURED_REPORT_NAME = "report.measured.html"
_SEAT = re.compile(r"R(?:[1-9]|1[0-6])\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
# Evidence labels, not coaching templates. Existing rule-based cues are never
# passed to the model or substituted for a failed generation.
_FLAGS = {
    "short_catch": "limited forward body angle at catch",
    "overreach": "lunging or over-reaching at catch",
    "over_compression": "over-compression at catch",
    "excess_layback": "excessive layback at finish",
    "no_layback": "little body swing at finish",
    "shooting_slide": "seat moving ahead of shoulders on drive",
    "early_arms": "arms bending early on drive",
    "early_body": "back opening early on drive",
    "rushed_recovery": "rushed recovery",
    "late_body_prep": "knees rising before body preparation",
}
_PRINCIPLES = {
    "short_catch": "Forward body angle is prepared by pivoting at the hips during recovery, before sliding toward the catch; lunging farther at the catch is not the aim.",
    "overreach": "Prepare a controlled hip pivot during recovery and avoid adding a last-moment shoulder lunge at the catch.",
    "over_compression": "A controlled slide stops at a comfortable catch position without forcing the knees beyond the available range.",
    "excess_layback": "The finish uses a controlled body swing rather than a large backward lean.",
    "no_layback": "The leg push leads into a controlled body swing before the arms finish the drive.",
    "shooting_slide": "The seat and shoulders stay connected as the legs begin the drive.",
    "early_arms": "The arms remain long during the initial leg push and bend later in the drive.",
    "early_body": "The legs lead the drive while the trunk angle stays steady initially; the body swing follows the leg push.",
    "rushed_recovery": "A relaxed recovery sequence allows the hands to move away and the body to prepare before the slide.",
    "late_body_prep": "Recovery follows hands away, body pivot, then the slide; body angle is prepared before the knees rise.",
}


class FeedbackError(ValueError):
    """Generation cannot safely be represented as LLM coaching feedback."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise FeedbackError("Metrics must contain finite JSON values") from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _number(value: Any, low: float, high: float, digits: int = 2) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or not low <= value <= high:
        return None
    return round(float(value), digits)


def extract_feedback_evidence(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded measurement data, excluding paths, people and raw strokes."""
    if not isinstance(metrics, dict) or not isinstance(metrics.get("rowers"), list):
        raise FeedbackError("The report has no measured rowers")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in metrics["rowers"]:
        if not isinstance(row, dict):
            raise FeedbackError("Invalid measured rower")
        seat = row.get("seat")
        if not isinstance(seat, str) or not _SEAT.fullmatch(seat) or seat in seen:
            raise FeedbackError("Rower identifiers must be unique report seat labels")
        seen.add(seat)
        summary = row.get("summary")
        if not isinstance(summary, dict):
            raise FeedbackError("Missing measured rower summary")
        count = _number(summary.get("n_strokes"), 0, 10000, 0)
        if not count:
            continue  # The report writer omits cards without usable strokes.
        flags = []
        for issue in summary.get("issues", [])[:3]:
            if not isinstance(issue, dict) or issue.get("code") not in _FLAGS:
                continue
            fraction = _number(issue.get("frac"), 0, 1)
            if fraction is None:
                continue
            flags.append({"code": issue["code"], "finding": _FLAGS[issue["code"]],
                          "flagged_fraction": fraction})
        tracking = summary.get("tracking", {})
        tracking = tracking if isinstance(tracking, dict) else {}
        total = _number(tracking.get("total_frames"), 1, 10000000, 0)
        observed = _number(tracking.get("observed_frames"), 0, total or 0, 0)
        rows.append({
            "seat": seat, "usable_strokes": int(count),
            "assessment": "preliminary" if count < 5 else "short_sample",
            "observed_frame_fraction": round(observed / total, 2)
                if observed is not None and total else None,
            "candidate_flags": flags,
        })
    if not rows or len(rows) > 16:
        raise FeedbackError("The report needs between one and sixteen measured rowers")
    cadence = metrics.get("crew_cadence", {})
    cadence = cadence if isinstance(cadence, dict) else {}
    return {
        "schema": SCHEMA_VERSION,
        "limits": "Projected video measurements; candidate flags are not coach validation.",
        "crew": {"cadence_state": "estimated" if cadence.get("state") == "estimated" else "unavailable",
                 "supporting_rowers": _number(cadence.get("supporting_rowers"), 0, len(rows), 0)},
        "rowers": rows,
    }


def build_feedback_request(metrics: Mapping[str, Any]) -> dict[str, Any]:
    evidence = extract_feedback_evidence(metrics)
    ids = [row["seat"] for row in evidence["rowers"]]
    rules = ("Use only the supplied measured evidence. Candidate flags are possible technique "
             "issues, not coach-verified findings. Do not invent defects, scores, validation or "
             "performance claims. Do not claim to have watched video. Write plain text, without "
             "numbers, digits, percentages, angles, timing values, seat IDs, links or markup. "
             "Do not discuss speed, power, injury or medicine. ")
    rower_requests = []
    for row in evidence["rowers"]:
        # Separate calls prevent a small local model from mixing evidence across
        # seats. Give one main candidate per call rather than competing cues.
        primary = row["candidate_flags"][:1]
        codes = [flag["code"] for flag in primary]
        selected = {"seat": row["seat"],
                    "candidate_flags": [{"code": flag["code"], "finding": flag["finding"]} for flag in primary],
                    "sample_status": "short preliminary sample" if row["assessment"] == "preliminary" else "short video sample"}
        instruction = ("Write coaching for this rower only. Return JSON with observation, cue and "
                       "evidence_codes. observation is a short sentence describing the supplied "
                       "candidate as a possible issue. cue is a short actionable rowing technique "
                       "suggestion for it. Keep each sentence under thirty words. ")
        if not codes:
            instruction += ("No consistent issue was flagged. Do not invent any fault. State that "
                            "no consistent issue was flagged and suggest maintaining the sequence. ")
            selected["finding_status"] = "No consistent technique issue was flagged in the measured sample."
        else:
            selected["relevant_rowing_principle"] = _PRINCIPLES[codes[0]]
            instruction += "Use the supplied rowing principle to explain a practical cue for this candidate. "
        if row["assessment"] == "preliminary":
            instruction += "Start observation with 'In this short sample' and then describe the candidate. "
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"observation": {"type": "string"}, "cue": {"type": "string"},
                    "evidence_codes": {"type": "array", "minItems": len(codes), "maxItems": len(codes),
                                       "items": {"type": "string", "enum": codes} if codes else {"type": "string"}}},
                  "required": ["observation", "cue", "evidence_codes"]}
        rower_requests.append({"seat": row["seat"], "response_schema": schema,
                               "prompt": instruction + rules + "\nEVIDENCE:\n" + _canonical(selected).decode("utf-8")})
    priorities: dict[str, int] = {}
    for row in evidence["rowers"]:
        for flag in row["candidate_flags"][:1]:
            priorities[flag["finding"]] = priorities.get(flag["finding"], 0) + 1
    crew_evidence = {"candidate_priorities": priorities, "short_video_sample": True,
                     "has_preliminary_rower": any(row["assessment"] == "preliminary" for row in evidence["rowers"])}
    crew_request = {
        "prompt": ("Write a brief crew coaching summary in JSON with only crew_summary. In under "
                   "forty words, suggest reviewing only the supplied candidate technique priorities. "
                   "Acknowledge the short sample. Do not state how many rowers have a finding, "
                   "rank rowers, or infer any other technique or timing issue. " + rules +
                   "\nEVIDENCE:\n" + _canonical(crew_evidence).decode("utf-8")),
        "response_schema": {"type": "object", "properties": {"crew_summary": {"type": "string"}},
                            "required": ["crew_summary"], "additionalProperties": False},
    }
    prompt = "\n\n".join([item["prompt"] for item in rower_requests] + [crew_request["prompt"]])
    return {"evidence": evidence, "expected_rower_ids": ids, "prompt": prompt,
            "rower_requests": rower_requests, "crew_request": crew_request,
            "input_sha256": _sha(_canonical(evidence)),
            "metrics_sha256": _sha(_canonical(metrics)),
            "prompt_sha256": _sha(_canonical({"rowers": rower_requests, "crew": crew_request}))}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FeedbackError("Duplicate fields in LLM response")
        result[key] = value
    return result


def _plain_text(value: Any, *, max_chars: int) -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= max_chars:
        raise FeedbackError("LLM feedback text is missing or exceeds its limit")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise FeedbackError("Control characters are not allowed in coaching text")
    value = " ".join(value.split())
    if re.search(r"[\d<>]|https?://|www\.|[\w.+-]+@[\w.-]+|```", value, re.I):
        raise FeedbackError("LLM prose must be plain text without numbers or links")
    if re.search(r"\b(?:percent(?:age)?|degrees?|milliseconds?|watts?|kilowatts?|"
                 r"zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twice|"
                 r"diagnos\w*|injur\w*|medic\w*|pain|guarantee\w*)\b", value, re.I):
        raise FeedbackError("Unsupported numerical or medical claims in LLM prose")
    return value


def _json_output(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 20000:
        raise FeedbackError("Invalid LLM response size")
    try:
        result = json.loads(raw.strip(), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FeedbackError("The LLM did not return the required JSON object") from exc
    if not isinstance(result, dict):
        raise FeedbackError("The LLM did not return a JSON object")
    return result


def _validate_rower(item: Any, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != {"observation", "cue", "evidence_codes"}:
        raise FeedbackError("Invalid per-rower LLM feedback structure")
    codes = item["evidence_codes"]
    allowed = {flag["code"] for flag in evidence["candidate_flags"]}
    if (not isinstance(codes, list) or len(codes) > 3
            or any(not isinstance(code, str) or code not in allowed for code in codes)
            or len(set(codes)) != len(codes) or (bool(allowed) != bool(codes))):
        raise FeedbackError("Coaching references findings absent from that rower's evidence")
    observation = _plain_text(item["observation"], max_chars=400)
    cue = _plain_text(item["cue"], max_chars=400)
    if not allowed and not re.search(r"\bno\b[^.!?]{0,45}\b(?:issues?|faults?|flags?)\b", observation, re.I):
        raise FeedbackError("No-flag rowers must explicitly state that no consistent issue was flagged")
    if evidence["assessment"] == "preliminary" and not re.search(
            r"\b(?:short|limited|preliminary|few|brief|insufficient)\s+(?:\w+\s+){0,3}(?:sample|clip|footage|evidence|strokes)\b", observation, re.I):
        raise FeedbackError("Preliminary rower feedback must acknowledge the limited sample")
    return {"observation": observation, "cue": cue, "evidence_codes": codes}


def parse_feedback_output(raw: str, request: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_output(raw)
    if set(result) != {"crew_summary", "rowers"}:
        raise FeedbackError("Unexpected LLM response fields")
    rowers = result["rowers"]
    if not isinstance(rowers, dict) or set(rowers) != set(request["expected_rower_ids"]):
        raise FeedbackError("LLM feedback must match all and only the measured rowers")
    checked = {"crew_summary": _plain_text(result["crew_summary"], max_chars=500), "rowers": {}}
    for evidence in request["evidence"]["rowers"]:
        seat = evidence["seat"]
        checked["rowers"][seat] = _validate_rower(rowers[seat], evidence)
    return checked


def generate_feedback(metrics: Mapping[str, Any], *,
                      generate: Callable[..., Mapping[str, Any]] | None = None) -> dict[str, Any]:
    request = build_feedback_request(metrics)
    if generate is None:
        from .local_llm import generate
    runtimes = []
    actual_prompts = []
    feedback: dict[str, Any] = {"rowers": {}}

    def invoke(item, check, max_tokens):
        prompt = item["prompt"]
        for attempt in range(2):
            runtime = generate(prompt, max_tokens=max_tokens, response_schema=item["response_schema"])
            if not isinstance(runtime, Mapping):
                raise FeedbackError("The local LLM returned no generation metadata")
            runtimes.append(runtime); actual_prompts.append(prompt)
            try:
                return check(_json_output(runtime.get("text")))
            except FeedbackError as exc:
                if attempt:
                    raise
                prompt = item["prompt"] + "\nCorrect this validation problem in your answer: " + str(exc)
        raise AssertionError("unreachable")

    for item, row in zip(request["rower_requests"], request["evidence"]["rowers"]):
        feedback["rowers"][item["seat"]] = invoke(item, lambda value, row=row: _validate_rower(value, row), 240)

    def check_crew(value):
        if set(value) != {"crew_summary"}:
            raise FeedbackError("Unexpected crew summary fields")
        return _plain_text(value["crew_summary"], max_chars=500)

    feedback["crew_summary"] = invoke(request["crew_request"], check_crew, 160)
    feedback = parse_feedback_output(json.dumps(feedback), request)
    runtime = runtimes[0]
    model = runtime.get("model")
    digest = runtime.get("model_sha256")
    if not isinstance(model, str) or not 1 <= len(model) <= 160 or "<" in model or ">" in model:
        raise FeedbackError("The generation has no valid model provenance")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise FeedbackError("The generation has no verified model digest")
    revision = runtime.get("model_revision")
    if not isinstance(revision, str) or len(revision) > 160:
        raise FeedbackError("The generation has no valid model revision")
    if any((item.get("model"), item.get("model_revision"), item.get("model_sha256")) !=
           (model, revision, digest) for item in runtimes):
        raise FeedbackError("All feedback must be generated by the same verified model")
    return {
        "schema_version": SCHEMA_VERSION, "state": "generated",
        "model": model, "model_revision": revision, "model_sha256": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": request["input_sha256"], "metrics_sha256": request["metrics_sha256"],
        "prompt_sha256": request["prompt_sha256"],
        "actual_prompts_sha256": _sha(_canonical(actual_prompts)),
        "response_sha256": _sha(_canonical([item["text"] for item in runtimes])), "feedback": feedback,
        "usage": {**{key: sum(float(item.get(key) or 0) for item in runtimes) for key in
                     ("prompt_tokens", "completion_tokens", "elapsed_seconds")}, "model_calls": len(runtimes)},
    }


def enrich_report_html(original_html: str, envelope: Mapping[str, Any],
                       metrics: Mapping[str, Any]) -> str:
    """Replace prose only; keep existing measured flags, media and charts."""
    from bs4 import BeautifulSoup
    request = build_feedback_request(metrics)
    if (envelope.get("state") != "generated" or envelope.get("schema_version") != SCHEMA_VERSION
            or envelope.get("input_sha256") != request["input_sha256"]
            or envelope.get("metrics_sha256") != request["metrics_sha256"]):
        raise FeedbackError("LLM feedback does not match this measured report")
    feedback = parse_feedback_output(json.dumps(envelope.get("feedback")), request)
    soup = BeautifulSoup(original_html, "html.parser")
    cards = {}
    for card in soup.select("section.card"):
        header = card.find("header", recursive=False)
        label = header.find("h2", recursive=False) if header else None
        seat = label.get_text(strip=True) if label else ""
        if _SEAT.fullmatch(seat):
            if seat in cards:
                raise FeedbackError("The HTML contains duplicate rower cards")
            cards[seat] = card
    if set(cards) != set(request["expected_rower_ids"]):
        raise FeedbackError("The measured rower cards do not match the LLM feedback")
    for node in soup.select("[data-strokesense-llm]"):
        node.decompose()
    for seat, card in cards.items():
        issues = card.find("ul", class_="issues", recursive=False)
        if not issues:
            raise FeedbackError("The report is missing a rower's existing feedback block")
        heading = issues.find_previous_sibling("h3")
        if heading:
            heading.string = "Measured candidate flags"
        # Existing rule cue text must never remain presented as LLM coaching.
        for cue in issues.select(".cue"):
            cue.decompose()
        for positive in issues.select("li.ok"):
            positive.string = "No consistent candidate flags in this sample."
        block = soup.new_tag("div", attrs={"data-strokesense-llm": "rower", "class": "llm-coaching"})
        title = soup.new_tag("h3")
        title.string = "LLM coaching feedback"
        block.append(title)
        observation = soup.new_tag("p")
        observation.string = feedback["rowers"][seat]["observation"]
        block.append(observation)
        cue = soup.new_tag("p")
        cue.string = feedback["rowers"][seat]["cue"]
        block.append(cue)
        issues.insert_before(block)
        if heading:
            block.insert_after(heading.extract())
    main = soup.find("main") or soup.body
    if main is None:
        raise FeedbackError("The report has no document body")
    overview = soup.new_tag("section", attrs={"class": "card wide", "data-strokesense-llm": "summary"})
    heading = soup.new_tag("h2")
    heading.string = "LLM coaching summary"
    overview.append(heading)
    summary = soup.new_tag("p")
    summary.string = feedback["crew_summary"]
    overview.append(summary)
    provenance = soup.new_tag("p", attrs={"class": "llm-provenance"})
    provenance.string = (f"Generated by {envelope['model']} · {envelope['generated_at']}. "
                         "Coaching text is based on this report's measurements; the numbers, "
                         "pictures and charts below are the measured analysis.")
    overview.append(provenance)
    first_card = main.select_one("section.card")
    if first_card:
        first_card.insert_before(overview)
    else:
        main.insert(0, overview)
    if soup.head:
        style = soup.new_tag("style", attrs={"data-strokesense-llm": "style"})
        style.string = (".llm-coaching{margin:16px 0;padding:14px 16px;background:#f1f8f4;"
                        "border-left:3px solid #287960;border-radius:5px}"
                        ".llm-coaching p{font-size:15px;line-height:1.6;margin:8px 0}"
                        ".llm-provenance{font-size:14px;line-height:1.5;color:#4c625e}")
        soup.head.append(style)
    return str(soup)


def _load_metrics(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FeedbackError("Invalid metrics document")
    return value


def feedback_status(report_path: str | Path) -> dict[str, Any]:
    report = Path(report_path)
    sidecar = report.with_name(SIDECAR_NAME)
    if not sidecar.is_file():
        return {"state": "missing"}
    try:
        envelope = json.loads(sidecar.read_text(encoding="utf-8"))
        request = build_feedback_request(_load_metrics(report.with_name("metrics.json")))
        if (not isinstance(envelope, dict) or envelope.get("schema_version") != SCHEMA_VERSION
                or envelope.get("state") != "generated"
                or envelope.get("input_sha256") != request["input_sha256"]
                or envelope.get("metrics_sha256") != request["metrics_sha256"]
                or envelope.get("prompt_sha256") != request["prompt_sha256"]
                or envelope.get("report_sha256") != _sha(report.read_bytes())
                or not _SHA256.fullmatch(str(envelope.get("model_sha256", "")))):
            return {"state": "outdated"}
        parse_feedback_output(json.dumps(envelope.get("feedback")), request)
        return {key: envelope[key] for key in ("state", "model", "generated_at",
                                                "input_sha256", "report_sha256")}
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "outdated"}


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".llm-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore_measured_report(report_path: str | Path) -> bool:
    """Remove stale generated prose before retrying or serving a failed retry.

    Restore the saved baseline only when its digest matches the baseline used
    for this enrichment. Otherwise remove our dedicated sections from the
    current document, retaining its current measured cards and pictures.
    """
    report = Path(report_path)
    current = report.read_bytes()
    if b"data-strokesense-llm" not in current:
        return False
    baseline = report.with_name(MEASURED_REPORT_NAME)
    restored = None
    try:
        envelope = json.loads(report.with_name(SIDECAR_NAME).read_text(encoding="utf-8"))
        candidate = baseline.read_bytes()
        if (_sha(candidate) == envelope.get("original_report_sha256")
                and _sha(current) == envelope.get("report_sha256")
                and b"data-strokesense-llm" not in candidate):
            restored = candidate
    except (OSError, ValueError, AttributeError):
        pass
    if restored is None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(current.decode("utf-8"), "html.parser")
        for node in soup.select("[data-strokesense-llm]"):
            node.decompose()
        restored = str(soup).encode("utf-8")
    _atomic_write(report, restored)
    return True


def write_feedback_report(report_path: str | Path, metrics_path: str | Path | None = None, *,
                          generate: Callable[..., Mapping[str, Any]] | None = None,
                          force: bool = False) -> dict[str, Any]:
    report = Path(report_path)
    metrics_file = Path(metrics_path) if metrics_path else report.with_name("metrics.json")
    if metrics_file != report.with_name("metrics.json"):
        raise FeedbackError("Report metrics must be the sibling metrics.json artifact")
    if not force and feedback_status(report)["state"] == "generated":
        cached = json.loads(report.with_name(SIDECAR_NAME).read_text(encoding="utf-8"))
        return {**cached, "cache_hit": True}
    # A failed retry must not leave older text labelled as current LLM output.
    restore_measured_report(report)
    metrics = _load_metrics(metrics_file)
    original = report.read_bytes()
    _atomic_write(report.with_name(MEASURED_REPORT_NAME), original)
    envelope = generate_feedback(metrics, generate=generate)
    rendered = enrich_report_html(original.decode("utf-8"), envelope, metrics).encode("utf-8")
    # No report changes take place until both model output and document structure
    # pass validation. A stale/missing sidecar never qualifies as generated.
    envelope["report_sha256"] = _sha(rendered)
    envelope["original_report_sha256"] = _sha(original)
    _atomic_write(report, rendered)
    _atomic_write(report.with_name(SIDECAR_NAME), _canonical(envelope))
    return {**envelope, "cache_hit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate grounded LLM coaching for a StrokeSense report")
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--force", action="store_true", help="Regenerate even when the current report is cached")
    arguments = parser.parse_args()
    try:
        result = write_feedback_report(arguments.report_path, force=arguments.force)
        print(json.dumps({key: result[key] for key in
                          ("state", "model", "generated_at", "input_sha256", "report_sha256", "cache_hit")}))
        return 0
    except Exception as exc:
        # No response text or potentially private source metadata is logged.
        print(json.dumps({"state": "failed", "error": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
