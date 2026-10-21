"""Crew-level analysis: pick out the rowers in a boat, order them by seat, and measure
how well their strokes line up in time."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import kinematics, strokes
from .pose import PoseResult


@dataclass
class Rower:
    tid: int
    seat: str = ""                  # "Stroke", "7", ..., "Bow" (or "Rower" for a single)
    k: kinematics.Kinematics | None = None
    strokes: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    handle: np.ndarray | None = None
    x_mean: float = 0.0
    sync_ms: float | None = None    # + = late relative to the crew, - = early
    sync_sd_ms: float | None = None


def _periodicity(sig, fps):
    """Strength of the dominant rhythm in the 12-50 spm band (0..1)."""
    x = sig - np.mean(sig)
    if np.std(x) < 1e-9 or len(x) < fps * 4:
        return 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac /= ac[0]
    lo, hi = int(fps * 60 / 50), min(len(ac) - 1, int(fps * 60 / 12))
    return float(ac[lo:hi].max()) if hi > lo else 0.0


def rowers_from_slots(pose: PoseResult, crew_dir: int, n_seats: int) -> list[Rower]:
    """Tracks keyed by seat slot (0 = leftmost on screen) from pose.crew_tracks."""
    rowers = []
    for slot in sorted(pose.tracks):
        k = kinematics.build(pose.dense(slot), pose.fps)
        r = Rower(tid=slot, k=k)
        r.strokes, r.handle = strokes.analyse(k)
        r.summary = strokes.summarise(r.strokes)
        # rowers face the stern: facing right means the rightmost seat is stroke
        seat = slot + 1 if crew_dir > 0 else n_seats - slot
        r.seat = "Stroke" if seat == n_seats else ("Bow" if seat == 1 else str(seat))
        if n_seats == 1:
            r.seat = "Rower"
        r.x_mean = float(slot)
        rowers.append(r)
    rowers.sort(key=lambda r: -(r.x_mean * crew_dir))
    return rowers


def find_rowers(pose: PoseResult, min_periodicity=0.3, max_rowers=9) -> list[Rower]:
    """Keep tracks that move like rowers (strong stroke rhythm, majority facing direction)."""
    cands = []
    for tid in pose.tracks:
        kp = pose.dense(tid)
        k = kinematics.build(kp, pose.fps)
        if k.visible.mean() < 0.4:
            continue
        per = _periodicity(np.where(k.visible, k.handle, np.median(k.handle)), pose.fps)
        if per < min_periodicity:
            continue                     # coach in the launch, cox, spectators...
        cands.append((tid, k, per))
    if not cands:
        return []
    facing = np.sign(np.sum([c[1].facing for c in cands])) or 1
    cands = [c for c in cands if c[1].facing == facing]          # cox faces the other way
    cands.sort(key=lambda c: -c[2])
    cands = cands[:max_rowers]
    rowers = []
    for tid, k, _ in cands:
        r = Rower(tid=tid, k=k)
        r.strokes, r.handle = strokes.analyse(k)
        r.summary = strokes.summarise(r.strokes)
        rowers.append(r)
    _relative_positions(rowers)
    _assign_seats(rowers, facing)
    return rowers


def _relative_positions(rowers: list[Rower]):
    """Position of each rower along the boat, robust to camera panning: the median x offset
    from a reference rower over the frames where both are visible."""
    if not rowers:
        return
    ref = max(rowers, key=lambda r: r.k.visible.sum())
    rx = ref.k.px["hip"][:, 0]
    for r in rowers:
        both = r.k.visible & ref.k.visible
        if both.sum() >= 5:
            r.x_mean = float(np.median(r.k.px["hip"][both, 0] - rx[both]))
        else:
            vis = r.k.visible
            r.x_mean = float(np.median(r.k.px["hip"][vis, 0] - np.median(rx[ref.k.visible]))) if vis.any() else 0.0


def _assign_seats(rowers: list[Rower], facing: int):
    """Rowers face the stern, so the one furthest in the facing direction is stroke seat.
    Seat spacing is estimated from neighbours so a rower we failed to track leaves a gap
    instead of shifting everyone's seat number."""
    if len(rowers) == 1:
        rowers[0].seat = "Rower"
        return
    rowers.sort(key=lambda r: -r.x_mean * facing)
    n = len(rowers)
    crew = 8 if n >= 5 else (4 if n >= 3 else n)
    idx = np.arange(n)
    if n < crew:
        # Some seats were not tracked: find the gaps. Neighbouring rowers sit about one body
        # apart, and perspective makes nearer rowers bigger, so measure gaps in torso lengths.
        pos = np.array([-r.x_mean * facing for r in rowers])
        size = np.array([r.k.scale_px for r in rowers])
        gaps = np.diff(pos) / ((size[:-1] + size[1:]) / 2)
        unit = float(np.median(gaps)) if len(gaps) else 1.0
        steps = np.clip(np.round(gaps / max(unit, 1e-6)), 1, None).astype(int)
        # never invent more empty seats than the boat has
        while 1 + steps.sum() > crew:
            steps[np.argmax(steps)] -= 1
        idx = np.concatenate([[0], np.cumsum(steps)])
    for i, r in zip(idx, rowers):
        seat = crew - int(i)
        r.seat = "Stroke" if seat == crew else ("Bow" if seat == 1 else str(seat))


def crew_sync(rowers: list[Rower], fps: float) -> dict:
    """Catch timing of each rower relative to the crew, from per-stroke catch times.

    For every crew catch (median across rowers) we take each rower's nearest catch and
    record the offset. Positive = late (catching after the crew), negative = early."""
    if len(rowers) < 2:
        return {}
    catches = {r.tid: np.array([s.catch_t for s in r.strokes] +
                               ([r.strokes[-1].next_catch_t] if r.strokes else []), float)
               for r in rowers}
    ref = max(catches.values(), key=len)
    if len(ref) == 0:
        return {}
    win = 0.25 * np.median(np.diff(ref)) if len(ref) > 1 else fps
    offsets = {r.tid: [] for r in rowers}
    for c in ref:
        near = {}
        for tid, cs in catches.items():
            if len(cs) == 0:
                continue
            j = int(np.argmin(np.abs(cs - c)))
            if abs(cs[j] - c) <= win:
                near[tid] = cs[j]
        if len(near) < max(2, len(rowers) // 2):
            continue
        crew_t = np.median(list(near.values()))
        for tid, t in near.items():
            offsets[tid].append((t - crew_t) / fps * 1000)
    out = {}
    for r in rowers:
        o = np.array(offsets[r.tid])
        if len(o) >= 2:
            r.sync_ms, r.sync_sd_ms = float(np.mean(o)), float(np.std(o))
            out[r.seat] = {"mean_ms": r.sync_ms, "sd_ms": r.sync_sd_ms, "n": len(o)}
    spread = [abs(v["mean_ms"]) for v in out.values()]
    return {"per_seat": out, "crew_spread_ms": float(np.mean(spread)) if spread else None}
