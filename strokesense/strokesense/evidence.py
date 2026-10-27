"""Deterministic, versioned evidence references for downstream coaching validation.

This is a measurement snapshot, not coach-approved advice. A content digest detects
accidental changes; without a signature or trusted storage it is not tamper-proof.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import hmac
import json
import math
from numbers import Real

from .strokes import FAULTS

SCHEMA_VERSION = 1
MIN_SAMPLE_STROKES = 3  # Engineering abstention heuristic, not empirical calibration.


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite(value, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return result


def _frame(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer frame")
    return value


def build_evidence_snapshot(
    metrics: Mapping, *, analysis_key: str, fps: float, start_seconds: float = 0.0
) -> dict:
    """Derive ID-addressable stroke/fault observations from saved report measurements.

    All IDs are scoped to an analysis request (caller supplies its source,
    model and configuration identity). The private request key is hashed and
    never embedded as plaintext. Fault prevalence uses observed/segmented
    strokes, NOT verified per-fault eligible strokes. Consequently coaching
    eligibility remains false until independent quality and cue review.
    """
    if not isinstance(analysis_key, str) or not analysis_key.strip():
        raise ValueError("analysis_key must be a non-empty string")
    fps = _finite(fps, "fps", positive=True)
    start_seconds = _finite(start_seconds, "start_seconds")
    if start_seconds < 0:
        raise ValueError("start_seconds cannot be negative")
    if not isinstance(metrics, Mapping) or not isinstance(metrics.get("rowers"), list):
        raise ValueError("metrics.rowers must be a list")

    analysis_id = "analysis_" + hashlib.sha256(
        ("strokesense:evidence:v1\0" + analysis_key).encode("utf-8")
    ).hexdigest()
    seats, observations, findings = [], [], []
    seen_seats = set()
    for rower in metrics["rowers"]:
        if not isinstance(rower, Mapping):
            raise ValueError("each rower must be a mapping")
        seat = rower.get("seat")
        if not isinstance(seat, str) or not seat.strip() or seat in seen_seats:
            raise ValueError("seat labels must be nonempty and unique")
        seen_seats.add(seat)
        raw_strokes = rower.get("strokes")
        if not isinstance(raw_strokes, list):
            raise ValueError("rower.strokes must be a list")
        seat_id = "seat_" + _digest([analysis_id, seat, str(rower.get("track"))])[:24]
        seen_indices = set()
        normalized = []
        for raw in raw_strokes:
            if not isinstance(raw, Mapping):
                raise ValueError("each stroke must be a mapping")
            idx = _frame(raw.get("idx"), "stroke index")
            if idx in seen_indices:
                raise ValueError(f"duplicate stroke index for seat {seat}")
            seen_indices.add(idx)
            catch = _frame(raw.get("catch"), "catch")
            finish = _frame(raw.get("finish"), "finish")
            next_catch = _frame(raw.get("next_catch"), "next_catch")
            if not catch < finish < next_catch:
                raise ValueError("stroke frames must satisfy catch < finish < next_catch")
            catch_subframe = _finite(raw.get("catch_t", catch), "catch_t")
            if abs(catch_subframe - catch) > 0.75:
                raise ValueError("catch_t must be close to the detected catch frame")
            codes = raw.get("faults", [])
            if not isinstance(codes, list) or any(
                not isinstance(code, str) or code not in FAULTS for code in codes
            ) or len(codes) != len(set(codes)):
                raise ValueError("faults must contain distinct known fault codes")
            stroke_id = "stroke_" + _digest(
                [analysis_id, seat_id, idx, catch, finish, next_catch]
            )[:24]
            normalized.append({
                "id": stroke_id,
                "seat_id": seat_id,
                "index": idx,
                "catch_frame": catch,
                "finish_frame": finish,
                "next_catch_frame": next_catch,
                "catch_seconds": round(start_seconds + catch_subframe / fps, 6),
                "finish_seconds": round(start_seconds + finish / fps, 6),
                "next_catch_seconds": round(start_seconds + next_catch / fps, 6),
                "fault_codes": sorted(codes),
            })

        normalized.sort(key=lambda item: item["index"])
        for before, after in zip(normalized, normalized[1:]):
            if after["catch_frame"] < before["next_catch_frame"]:
                raise ValueError("a seat has overlapping or out-of-order strokes")
        n = len(normalized)
        seats.append({
            "id": seat_id,
            "seat": seat,
            "analyzed_strokes": n,
            "status": "candidate_unreviewed" if n >= MIN_SAMPLE_STROKES else "insufficient_strokes",
        })
        observations.extend(normalized)
        for fault_code in sorted({
            code for record in normalized for code in record["fault_codes"]
        }):
            affected_ids = [record["id"] for record in normalized
                            if fault_code in record["fault_codes"]]
            findings.append({
                "id": "finding_" + _digest([analysis_id, seat_id, fault_code, affected_ids])[:24],
                "seat_id": seat_id,
                "fault_code": fault_code,
                "stroke_ids": affected_ids,
                "observed_count": len(affected_ids),
                "analyzed_strokes": n,
                "observed_fraction": len(affected_ids) / n,
                "eligible_strokes": None,
                "status": "candidate_unreviewed" if n >= MIN_SAMPLE_STROKES else "insufficient_evidence",
                "coaching_eligible": False,
            })

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "fps": fps,
        "start_seconds": start_seconds,
        "status": "candidate_unreviewed" if any(
            seat["analyzed_strokes"] >= MIN_SAMPLE_STROKES for seat in seats
        ) else "insufficient_evidence",
        "seats": seats,
        "strokes": observations,
        "findings": findings,
        "quality_limitations": [
            "per_fault_eligible_strokes_unknown",
            "pose_and_segmentation_accuracy_not_empirically_verified",
            "coaching_cues_not_coach_approved",
        ],
    }
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return snapshot


def verify_evidence_snapshot(snapshot) -> bool:
    """Detect changed snapshot contents; NOT an authenticity signature."""
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEMA_VERSION:
        return False
    claimed = snapshot.get("snapshot_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        return False
    try:
        payload = {key: value for key, value in snapshot.items()
                   if key != "snapshot_sha256"}
        return hmac.compare_digest(claimed, _digest(payload))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_public_evidence_snapshot(snapshot) -> bool:
    """Strict v1 schema/invariant check for the *unreviewed* local viewer.

    The SHA-256 field is an accidental-corruption check, not authentication.
    This guard must not mistake a rehashed but structurally invalid record for
    a verified measurement or a coach-approved release.
    """
    if not verify_evidence_snapshot(snapshot):
        return False

    def number(value, *, positive=False, nonnegative=False):
        return (type(value) in (float, int) and math.isfinite(value)
                and (not positive or value > 0)
                and (not nonnegative or value >= 0))

    def nonnegative_int(value):
        return type(value) is int and value >= 0

    def valid_id(value):
        return (isinstance(value, str) and 0 < len(value) <= 128
                and all(c.isalnum() or c in "_-" for c in value))

    try:
        if set(snapshot) != {
            "schema_version", "analysis_id", "fps", "start_seconds",
            "status", "seats", "strokes", "findings",
            "quality_limitations", "snapshot_sha256",
        }:
            return False
        fps, start = snapshot["fps"], snapshot["start_seconds"]
        if (not valid_id(snapshot["analysis_id"]) or
                not number(fps, positive=True) or
                not number(start, nonnegative=True)):
            return False
        limits = snapshot["quality_limitations"]
        if (not isinstance(limits, list) or len(limits) > 50 or any(
            not isinstance(item, str) or len(item) > 256 for item in limits
        )):
            return False
        seats, strokes, findings = (snapshot[name] for name in
                                    ("seats", "strokes", "findings"))
        if any(not isinstance(items, list) or len(items) > 5000 for items
               in (seats, strokes, findings)):
            return False

        seat_map = {}
        for row in seats:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "seat", "analyzed_strokes", "status"}):
                return False
            sid = row["id"]
            if (not valid_id(sid) or sid in seat_map or
                    not isinstance(row["seat"], str) or
                    not 0 < len(row["seat"]) <= 80 or
                    not nonnegative_int(row["analyzed_strokes"])):
                return False
            n = row["analyzed_strokes"]
            expected_status = ("candidate_unreviewed" if n >= MIN_SAMPLE_STROKES
                               else "insufficient_strokes")
            if row["status"] != expected_status:
                return False
            seat_map[sid] = row

        stroke_map, counts, indices, fault_map = {}, {}, {}, {}
        intervals = {}
        for row in strokes:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "seat_id", "index", "catch_frame", "finish_frame",
                    "next_catch_frame", "catch_seconds", "finish_seconds",
                    "next_catch_seconds", "fault_codes"}):
                return False
            sid, rid = row["seat_id"], row["id"]
            if (sid not in seat_map or not valid_id(rid) or rid in stroke_map
                    or not nonnegative_int(row["index"])):
                return False
            frame_keys = ("catch_frame", "finish_frame", "next_catch_frame")
            frames = [row[key] for key in frame_keys]
            if (not all(nonnegative_int(v) for v in frames) or
                    not frames[0] < frames[1] < frames[2]):
                return False
            times = [row[key] for key in
                     ("catch_seconds", "finish_seconds", "next_catch_seconds")]
            if (not all(number(v, nonnegative=True) for v in times) or
                    not times[0] < times[1] < times[2] or
                    any(abs(times[i] - (start + frames[i] / fps)) >
                        (1.0 / fps + 1e-5 if i == 0 else 1e-5)
                        for i in range(3))):
                return False
            codes = row["fault_codes"]
            if (not isinstance(codes, list) or
                    any(not isinstance(code, str) or code not in FAULTS
                        for code in codes) or len(set(codes)) != len(codes)):
                return False
            key = (sid, row["index"])
            if key in indices:
                return False
            indices[key] = True
            intervals.setdefault(sid, []).append(
                (row["index"], frames[0], frames[2])
            )
            counts[sid] = counts.get(sid, 0) + 1
            stroke_map[rid] = row
            for code in codes:
                fault_map.setdefault((sid, code), set()).add(rid)

        if any(counts.get(sid, 0) != row["analyzed_strokes"]
               for sid, row in seat_map.items()):
            return False
        # A rehashed snapshot is still invalid if a seat's chronological
        # stroke sequence overlaps or reverses, even when each interval
        # independently has valid catch/finish/next-catch frame order.
        for entries in intervals.values():
            ordered = sorted(entries)
            if any(later[1] < earlier[2]
                   for earlier, later in zip(ordered, ordered[1:])):
                return False

        finding_keys, finding_ids = set(), set()
        for row in findings:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "seat_id", "fault_code", "stroke_ids",
                    "observed_count", "analyzed_strokes", "observed_fraction",
                    "eligible_strokes", "status", "coaching_eligible"}):
                return False
            sid, code = row["seat_id"], row["fault_code"]
            key = (sid, code)
            if (not valid_id(row["id"]) or row["id"] in finding_ids or
                    sid not in seat_map or code not in FAULTS or
                    key in finding_keys):
                return False
            finding_keys.add(key)
            finding_ids.add(row["id"])
            ids = row["stroke_ids"]
            expected_ids = fault_map.get(key, set())
            if (not isinstance(ids, list) or
                    any(not isinstance(x, str) for x in ids) or
                    len(ids) != len(set(ids)) or set(ids) != expected_ids or
                    not nonnegative_int(row["observed_count"]) or
                    row["observed_count"] != len(expected_ids) or
                    row["analyzed_strokes"] != seat_map[sid]["analyzed_strokes"] or
                    not number(row["observed_fraction"]) or
                    row["observed_count"] < 1 or
                    not math.isclose(row["observed_fraction"],
                                     row["observed_count"] / row["analyzed_strokes"],
                                     rel_tol=0, abs_tol=1e-9) or
                    row["eligible_strokes"] is not None or
                    row["coaching_eligible"] is not False):
                return False
            expected_status = ("candidate_unreviewed"
                               if row["analyzed_strokes"] >= MIN_SAMPLE_STROKES
                               else "insufficient_evidence")
            if row["status"] != expected_status:
                return False

        expected_top = ("candidate_unreviewed" if any(
            row["analyzed_strokes"] >= MIN_SAMPLE_STROKES for row in seats
        ) else "insufficient_evidence")
        return (finding_keys == set(fault_map) and
                snapshot["status"] == expected_top)
    except (TypeError, ValueError, KeyError, OverflowError, ZeroDivisionError):
        return False
