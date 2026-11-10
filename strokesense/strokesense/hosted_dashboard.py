"""Bounded, measured-data JSON for the Vercel-native StrokeSense dashboard.

No private study or reviewer records are accessed. The prepared and temporary
visitor reports each expose only their own completed metrics and optional,
verified LLM coaching sidecar.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from .oneclick_demo import MAX_METRICS_BYTES, _safe_result, summarize_crew_metrics

_SEAT = re.compile(r"R(?:[1-9]|1[0-6])\Z")


def _number(value, minimum=-1e9, maximum=1e9):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    value = float(value)
    return value if minimum <= value <= maximum else None


def _integer(value, minimum=0, maximum=10_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        return None
    return value


def _text(value, limit=400):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 0 < len(value) <= limit else None


def _json_file(path: Path, root: Path, limit: int):
    if not _safe_result(root, path) or path.stat().st_size > limit:
        raise ValueError("report_data_unavailable")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("invalid_report_data")
    return result


def _verified_feedback(report: Path, root: Path):
    """Never label unverified or unmatched sidecar content as LLM feedback."""
    try:
        from .llm_feedback import feedback_status, SIDECAR_NAME

        path = report.with_name(SIDECAR_NAME)
        if not _safe_result(root, path) or path.stat().st_size > 256 * 1024:
            return {}
        if feedback_status(report).get("state") != "generated":
            return {}
        envelope = _json_file(path, root, 256 * 1024)
        feedback = envelope.get("feedback")
        if not isinstance(feedback, dict):
            return {}
        rowers = feedback.get("rowers")
        if not isinstance(rowers, dict):
            return {}
        return {
            "crew_summary": _text(feedback.get("crew_summary"), 500),
            "model": _text(envelope.get("model"), 160),
            "generated_at": _text(envelope.get("generated_at"), 80),
            "rowers": rowers,
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {}


def _verified_seat_mapping(raw, rower_ids):
    """Only display complete, self-consistent eight-seat mappings from the CLI."""
    uncertain = {
        "status": "uncertain", "travel_direction": None, "confidence": None,
        "assignments": {}, "reason": "Boat direction could not be verified from this clip.",
        "source": None,
    }
    if not isinstance(raw, dict):
        return uncertain
    if raw.get("status") != "auto":
        return {**uncertain, "reason": _text(raw.get("reason"), 240) or uncertain["reason"],
                "confidence": _number(raw.get("confidence"), 0, 1)}
    direction = raw.get("travel_direction")
    confidence = _number(raw.get("confidence"), .82, 1)
    assignments = raw.get("assignments")
    expected_ids = {f"R{i}" for i in range(1, 9)}
    labels = ["Bow seat"] + [f"Seat {i}" for i in range(2, 8)] + ["Stroke seat"]
    if (direction not in ("left", "right") or confidence is None
            or set(rower_ids) != expected_ids or not isinstance(assignments, dict)
            or set(assignments) != expected_ids):
        return uncertain
    expected = {
        f"R{i+1}": labels[i if direction == "left" else 7-i] for i in range(8)
    }
    if any(assignments[k] != label for k, label in expected.items()):
        return uncertain
    return {
        "status": "auto", "travel_direction": direction, "confidence": confidence,
        "assignments": expected,
        "reason": _text(raw.get("reason"), 240) or
            "Estimated from rower-facing pose and stable left-to-right tracking.",
        "source": "pose_orientation_and_spatial_order",
    }


def build_dashboard(state, clip_name: str):
    """Return a finite, bounded subset of a completed run's measured report."""
    if state.snapshot().get("state") != "finished":
        raise ValueError("report_not_ready")
    report = state.report
    root = state.output_root
    if report is None or not _safe_result(root, report):
        raise ValueError("report_not_ready")
    metrics = _json_file(report.with_name("metrics.json"), root, MAX_METRICS_BYTES)
    crew = summarize_crew_metrics(metrics)
    measured_rows = metrics.get("rowers", [])
    if not isinstance(measured_rows, list) or len(measured_rows) > 16:
        raise ValueError("invalid_report_data")
    feedback = _verified_feedback(report, root)
    coaching_rows = feedback.get("rowers", {})
    cadence = metrics.get("crew_cadence", {})
    cadence = cadence if isinstance(cadence, dict) else {}
    sync = metrics.get("sync", {})
    sync = sync if isinstance(sync, dict) else {}

    range_value = cadence.get("rate_range_spm")
    supported_range = None
    if isinstance(range_value, (list, tuple)) and len(range_value) == 2:
        low = _number(range_value[0], 5, 90)
        high = _number(range_value[1], 5, 90)
        if low is not None and high is not None and low <= high:
            supported_range = [round(low, 1), round(high, 1)]

    rowers = []
    for row in measured_rows:
        if not isinstance(row, dict):
            continue
        seat = row.get("seat")
        if not isinstance(seat, str) or not _SEAT.fullmatch(seat):
            continue
        summary = row.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        tracking = summary.get("tracking", {})
        tracking = tracking if isinstance(tracking, dict) else {}
        issues = summary.get("issues", [])
        issues = issues if isinstance(issues, list) else []
        flags = []
        for item in issues[:3]:
            if not isinstance(item, dict):
                continue
            label = _text(item.get("title"), 140)
            frac = _number(item.get("frac"), 0, 1)
            if label and frac is not None:
                flags.append({"label": label, "percentage": round(frac * 100)})
        llm_row = coaching_rows.get(seat, {})
        llm_row = llm_row if isinstance(llm_row, dict) else {}
        offset = _number(row.get("sync_ms"), -10000, 10000)
        rowers.append({
            "id": seat,
            "usable_cycles": _integer(summary.get("n_strokes"), 0, 10000),
            "observed_frames": _integer(tracking.get("observed_frames")),
            "sampled_frames": _integer(tracking.get("total_frames")),
            "score": _number(summary.get("score"), 0, 100),
            "consistency": _number(summary.get("consistency"), 0, 100),
            "recovery_drive_ratio": _number(summary.get("ratio"), 0, 20),
            "body_angle_catch_deg": _number(summary.get("trunk_catch"), -180, 180),
            "body_angle_finish_deg": _number(summary.get("trunk_finish"), -180, 180),
            "catch_offset_ms": offset,
            "catch_timing_label": "late" if offset is not None and offset > 0 else (
                "early" if offset is not None and offset < 0 else (
                    "on time" if offset == 0 else None)),
            "flags": flags,
            "coaching": {
                "finding": _text(llm_row.get("observation"), 500),
                "action": _text(llm_row.get("cue"), 500),
            },
            "snapshots": [],
        })
    if not rowers:
        raise ValueError("invalid_report_data")
    completed = _number(getattr(state, "last_end", None), 0, 32503680000)
    generated_at = feedback.get("generated_at")
    if generated_at is None and completed is not None:
        generated_at = datetime.fromtimestamp(completed, timezone.utc).isoformat()
    return {
        "clip_name": _text(clip_name, 120) or "Rowing clip",
        "run_id": state.run_id if isinstance(getattr(state, "run_id", None), str)
            and re.fullmatch(r"[0-9a-f]{32}", state.run_id) else None,
        "generated_at": generated_at,
        "summary": {
            "candidate_rowers": crew["candidate_rowers"],
            "observed_cycles": crew["observed_cycles"],
            "shared_rate_spm": crew["shared_rate_spm"],
            "clip_duration_s": None,
            "coach_summary": feedback.get("crew_summary"),
            "model": feedback.get("model"),
        },
        "cadence": {
            "supported_range_spm": supported_range,
            "supported_seconds": _number(cadence.get("support_duration_seconds"), 0, 3600),
            "catch_offset_ms": _number(sync.get("crew_spread_ms"), 0, 10000),
        },
        "rowers": rowers,
        "seat_mapping": _verified_seat_mapping(sync.get("seat_mapping"), [r["id"] for r in rowers]),
        "limits": "Model candidate tracks and projected 2D measurements; findings require coach review.",
    }
