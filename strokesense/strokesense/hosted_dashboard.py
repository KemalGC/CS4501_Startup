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
from .strokes import FAULTS

_SEAT = re.compile(r"R(?:[1-9]|1[0-6])\Z")
_SNAPSHOT_NAME = re.compile(
    r"(?:seat_R(?:[1-9]|1[0-6])_(?:catch|finish)|"
    r"fault_[0-9]{1,4}_(?:" + "|".join(re.escape(code) for code in FAULTS) +
    r")(?:_(?:before|after))?)\.jpg\Z"
)
MAX_SNAPSHOT_BYTES = 512 * 1024
_EIGHT_TRACK_IDS = {f"R{i}" for i in range(1, 9)}
# The known prepared eights clip was visually checked: its tracked rowers run
# from stroke (R1, left of frame) to bow (R8, right of frame).  This is NOT a
# general rule for uploaded videos, where tracking IDs are screen-order IDs.
_PREPARED_EIGHT_SEATS = {
    f"R{i}": ("Stroke seat" if i == 1 else "Bow seat" if i == 8
               else f"Seat {9 - i}")
    for i in range(1, 9)
}


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


def _snapshot_path(report: Path, root: Path, filename):
    """Resolve only bounded, actual generated JPEGs beside this run's report."""
    if not isinstance(filename, str) or not _SNAPSHOT_NAME.fullmatch(filename):
        return None
    path = report.with_name(filename)
    try:
        if (not _safe_result(root, path) or not 4 <= path.stat().st_size <= MAX_SNAPSHOT_BYTES):
            return None
        return path
    except (OSError, ValueError):
        return None


def _gallery_manifest(report: Path, root: Path):
    """A missing manifest is normal for older completed analyses."""
    path = report.with_name('mistake_frames.json')
    if not path.exists():
        return None
    try:
        raw = _json_file(path, root, 128 * 1024)
        rows = raw.get('rowers')
        if raw.get('version') != 1 or not isinstance(rows, dict) or len(rows) > 16:
            return {}
        return rows
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _rower_gallery(report, root, seat, track, issues, gallery_rows, snapshots_base):
    """Serve only real images in this report and flags in its measured metrics."""
    raw = gallery_rows.get(seat, {}) if isinstance(gallery_rows, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    valid_flags = {item.get('code') for item in issues if isinstance(item, dict)
                   and isinstance(item.get('code'), str) and item['code'] in FAULTS}

    def exposed(photo, expected_filename):
        if not isinstance(photo, dict):
            return None
        filename = photo.get('filename')
        if filename != expected_filename or _snapshot_path(report, root, filename) is None:
            return None
        label = _text(photo.get('label'), 40)
        when = _number(photo.get('time_seconds'), 0, 1_000_000)
        if label not in ('Before', 'Flagged moment', 'After', 'Catch reference', 'Finish reference'):
            return None
        return {'label': label, 'time_seconds': when,
                'url': f'{snapshots_base}/{filename}'}

    # Analyses created before the progression feature still have two valid
    # real snapshots. Do not reattribute stale photos on reruns with a manifest.
    if gallery_rows is None:
        legacy = [('catch', 'Catch reference'), ('finish', 'Finish reference')]
        flagged = []
        for issue in issues[:3]:
            if (not isinstance(issue, dict) or not isinstance(issue.get('code'), str)
                    or issue['code'] not in valid_flags):
                continue
            code = issue['code']
            filename = f"fault_{track}_{code}.jpg" if track is not None else None
            if filename is not None and _snapshot_path(report, root, filename) is not None:
                flagged = [{
                    'label': f"Candidate: {FAULTS[code]['title']}",
                    'time_seconds': None, 'url': f'{snapshots_base}/{filename}',
                }]
                break
        snapshots = [
            {'label': label, 'time_seconds': None,
             'url': f'{snapshots_base}/seat_{seat}_{kind}.jpg'}
            for kind, label in legacy
            if _snapshot_path(report, root, f'seat_{seat}_{kind}.jpg') is not None
        ]
        return [], flagged + snapshots

    snapshots = []
    for photo in raw.get('snapshots', [])[:2] if isinstance(raw.get('snapshots'), list) else []:
        reference_name = {'Catch reference': f'seat_{seat}_catch.jpg',
                          'Finish reference': f'seat_{seat}_finish.jpg'}
        available = exposed(photo, reference_name.get(photo.get('label'))
                            if isinstance(photo, dict) else None)
        if available:
            snapshots.append(available)

    sequences = []
    listed = raw.get('mistake_sequences', [])
    for item in listed[:3] if isinstance(listed, list) else []:
        if (not isinstance(item, dict) or not isinstance(item.get('code'), str)
                or item['code'] not in valid_flags):
            continue
        code = item['code']
        stroke = _integer(item.get('stroke'), 0, 10000)
        photos = item.get('frames', [])
        if stroke is None or track is None or not isinstance(photos, list):
            continue
        expected = {
            'Before': f'fault_{track}_{code}_before.jpg',
            'Flagged moment': f'fault_{track}_{code}.jpg',
            'After': f'fault_{track}_{code}_after.jpg',
        }
        checked = [image for photo in photos[:3] if isinstance(photo, dict)
                   and (image := exposed(photo, expected.get(photo.get('label'))))]
        if (not any(image['label'] == 'Flagged moment' for image in checked)
                or any(image['time_seconds'] is None for image in checked)):
            continue
        checked.sort(key=lambda image: image['time_seconds'])
        if len({image['url'] for image in checked}) != len(checked):
            continue
        sequences.append({'code': code, 'label': FAULTS[code]['title'],
                          'stroke': stroke, 'frames': checked})
    return sequences, snapshots


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
    expected_ids = _EIGHT_TRACK_IDS
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


def _report_seat_mapping(raw, rower_ids, *, prepared: bool = False):
    """Present seats only with eight intact identities and verified orientation.

    The prepared reference's orientation was confirmed from the supplied image;
    visitor uploads instead use the conservative pose-based mapping and may
    remain unassigned.  The model's R-numbers are never changed.
    """
    if prepared and len(rower_ids) == 8 and set(rower_ids) == _EIGHT_TRACK_IDS:
        return {
            "status": "prepared", "travel_direction": "right", "confidence": None,
            "assignments": dict(_PREPARED_EIGHT_SEATS),
            "reason": "Visual seat order for this prepared eight: R1 is Seat 8 (Stroke); R8 is Seat 1 (Bow).",
            "source": "prepared_reference_visual_order",
        }
    return _verified_seat_mapping(raw, rower_ids)


def build_dashboard(state, clip_name: str, *, prepared: bool = False,
                    snapshots_base: str = '/demo/snapshots'):
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
    gallery_rows = _gallery_manifest(report, root)
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
        observation = _text(llm_row.get("observation"), 500)
        cue = _text(llm_row.get("cue"), 500)
        offset = _number(row.get("sync_ms"), -10000, 10000)
        track_value = row.get("track")
        track = None
        if type(track_value) is int and 0 <= track_value <= 9999:
            track = track_value
        elif (type(track_value) is float and math.isfinite(track_value)
              and track_value.is_integer() and 0 <= track_value <= 9999):
            track = int(track_value)
        sequences, photos = _rower_gallery(
            report, root, seat, track, issues, gallery_rows, snapshots_base)
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
                "finding": observation,
                "action": cue,
                # Flags and metric scores are measured heuristics, not a generated
                # coaching narrative. Let the UI distinguish the two states.
                "source": "verified_llm" if observation or cue else "not_generated",
            },
            "snapshots": photos,
            "mistake_sequences": sequences,
        })
    if not rowers:
        raise ValueError("invalid_report_data")
    seat_mapping = _report_seat_mapping(
        sync.get("seat_mapping"), [r["id"] for r in rowers], prepared=prepared)
    assignments = seat_mapping["assignments"]
    for rower in rowers:
        rower["seat_label"] = assignments.get(rower["id"])
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
        "seat_mapping": seat_mapping,
        "limits": "Model candidate tracks and projected 2D measurements; findings require coach review.",
    }
