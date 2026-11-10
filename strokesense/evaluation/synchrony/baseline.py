"""Frozen original reference-rower timing association."""
from __future__ import annotations
import numpy as np
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
