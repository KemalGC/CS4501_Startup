"""Stroke segmentation, per-stroke technique metrics, and fault detection."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
from scipy.signal import find_peaks

from .kinematics import Kinematics, smooth

# --------------------------------------------------------------------------- fault catalogue
# Thresholds are coaching heuristics for side-on 2D video; they are deliberately conservative
# and live in one place so a coach can tune them.
FAULTS = {
    "short_catch": dict(
        title="Not enough body angle at the catch",
        cue="Pivot forward from the hips before the slide — arrive at the catch with shoulders ahead of the hips (about 1 o'clock).",
        severity=2),
    "overreach": dict(
        title="Lunging / over-reaching at the catch",
        cue="Set the body angle early in the recovery and hold it; don't throw the shoulders at the catch.",
        severity=2),
    "over_compression": dict(
        title="Over-compressed at the catch",
        cue="Stop the slide when the shins are vertical — going further loses leg power and drops the shoulders.",
        severity=2),
    "excess_layback": dict(
        title="Too much layback at the finish",
        cue="Finish at about 11 o'clock; leaning further makes the recovery slow and hard to start.",
        severity=1),
    "no_layback": dict(
        title="Upright finish (little body swing)",
        cue="Let the body swing through past vertical before the arms draw in — it adds length to every stroke.",
        severity=1),
    "shooting_slide": dict(
        title="Shooting the slide",
        cue="Hang off the handle as the legs go down — the seat and the shoulders should move together off the catch.",
        severity=3),
    "early_arms": dict(
        title="Breaking the arms early",
        cue="Keep the arms long like ropes until the legs are nearly down; the arms finish the stroke, they don't start it.",
        severity=2),
    "early_body": dict(
        title="Opening the back too early",
        cue="Let the legs lead — hold the body angle through the first half of the drive.",
        severity=2),
    "rushed_recovery": dict(
        title="Rushing the slide",
        cue="Take roughly twice as long on the recovery as the drive at low rates; let the boat run under you.",
        severity=2),
    "late_body_prep": dict(
        title="Knees up before the body is set",
        cue="Hands away, body over, then slide — the body angle should be set before the knees rise.",
        severity=2),
}


@dataclass
class Stroke:
    idx: int
    catch: int              # frame index
    catch_t: float          # sub-frame catch time (frames), for crew timing
    finish: int
    next_catch: int
    rate: float             # strokes per minute
    drive_s: float
    recovery_s: float
    ratio: float            # recovery / drive
    length: float           # handle travel catch->finish, torso lengths
    trunk_catch: float      # degrees from vertical, + = forward
    trunk_finish: float
    thigh_catch: float
    elbow_catch: float
    shin_catch: float | None = None
    shoot_deg: float = 0.0  # how much the body angle closed early in the drive
    arm_bend_at_legs: float = 0.0   # elbow flexion (deg) before legs ~70% down
    body_open_at_legs: float = 0.0  # fraction of body swing done when legs 40% down
    body_set_at_knees: float = 1.0  # fraction of body angle set when knees 30% up
    next_catch_t: float = 0.0
    faults: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _refine_peak(y, i):
    """Sub-frame peak position by parabolic interpolation."""
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-9:
            return i + 0.5 * (a - c) / den
    return float(i)


def periodicity(sig, fps, min_rate=12, max_rate=50):
    """Strength (0..1) of the dominant rhythm in the rowing band."""
    x = np.asarray(sig, float) - np.mean(sig)
    if np.std(x) < 1e-9 or len(x) < fps * 4:
        return 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac /= ac[0]
    lo, hi = int(fps * 60 / max_rate), min(len(ac) - 1, int(fps * 60 / min_rate))
    return float(ac[lo:hi].max()) if hi > lo else 0.0


def find_strokes(k: Kinematics, min_rate=12, max_rate=50):
    """Return list of (catch, finish, next_catch) frame indices."""
    h = smooth(k.handle, k.fps, 0.25)
    vis = k.visible if k.visible.any() else np.ones(len(h), bool)

    def z(x):
        lo, hi = np.percentile(x[vis], [5, 95])
        return (x - lo) / (hi - lo + 1e-9)

    # Catch = hands at full reach, knees up, body forward. Each cue is weighted by how cleanly
    # rhythmic it is in this clip, so one badly tracked joint (a hidden wrist) can't derail it.
    cues = [z(h)]
    if k.reliable.get("knee"):
        cues.append(z(smooth(k.angles["thigh"], k.fps, 0.25)))
    else:   # body angle peaks a little after the catch, so only use it when the knees are hidden
        cues.append(z(smooth(k.angles["trunk"], k.fps, 0.25)))
    q = np.array([max(periodicity(c, k.fps), 0.05) ** 2 for c in cues])
    if k.reliable.get("knee"):
        q[1] = max(q[1], 1.8 * q[0])     # knees-up is the most precise catch marker when visible
    c_sig = sum(w * c for w, c in zip(q / q.sum(), cues))
    min_dist = int(k.fps * 60 / max_rate * 0.8)
    catches, _ = find_peaks(c_sig, prominence=0.3, distance=max(1, min_dist))
    out = []
    for c0, c1 in zip(catches[:-1], catches[1:]):
        period_s = (c1 - c0) / k.fps
        if not (60 / max_rate <= period_s <= 60 / min_rate):
            continue
        if k.visible[c0:c1 + 1].mean() < 0.7:
            continue
        f = c0 + int(np.argmin(c_sig[c0:c1 + 1]))
        if f in (c0, c1):
            continue
        # the drive is ~25-60% of the stroke cycle; outside that the segmentation is unreliable
        if not (0.2 <= (f - c0) / (c1 - c0) <= 0.65):
            continue
        out.append((int(c0), int(f), int(c1)))
    refined = {int(c): _refine_peak(c_sig, int(c)) for c in catches}
    return out, h, refined


def _progress(sig, start, end):
    """Normalised 0->1 progress of a signal from its value at `start` to its value at `end`."""
    a, b = sig[start], sig[end]
    if abs(b - a) < 1e-6:
        return np.zeros(end - start + 1)
    return np.clip((sig[start:end + 1] - a) / (b - a), -0.5, 1.5)


def _first_at(prog, level):
    hits = np.nonzero(prog >= level)[0]
    return int(hits[0]) if len(hits) else len(prog) - 1


def analyse(k: Kinematics):
    """Segment strokes, compute metrics and flag faults for one rower."""
    segs, h, refined = find_strokes(k)
    A = {name: smooth(v, k.fps, 0.2) for name, v in k.angles.items()}
    # Only judge a body part we can actually see well
    if segs:
        travel = np.median([h[c] - h[f] for c, f, _ in segs])
    else:
        travel = 0
    arms_ok = travel >= 1.0 and k.reliable.get("elbow", False)
    shins_ok = "shin" in A and float(np.mean(k.conf["ankle"] >= 0.5)) >= 0.8
    legs_ok = k.reliable.get("knee", False)
    strokes = []
    for i, (c, f, n) in enumerate(segs):
        drive = (f - c) / k.fps
        rec = (n - f) / k.fps
        s = Stroke(
            idx=i, catch=c, catch_t=refined.get(c, float(c)), finish=f, next_catch=n,
            rate=60.0 / ((n - c) / k.fps), drive_s=drive, recovery_s=rec, ratio=rec / max(drive, 1e-6),
            length=float(h[c] - h[f]),
            trunk_catch=float(A["trunk"][c]), trunk_finish=float(A["trunk"][f]),
            thigh_catch=float(A["thigh"][c]), elbow_catch=float(A["elbow"][c]),
            shin_catch=float(A["shin"][c]) if shins_ok else None,
            next_catch_t=refined.get(n, float(n)),
        )
        # ---- drive sequencing (catch -> finish)
        legs = _progress(A["thigh"], c, f)          # 0 at catch, 1 when thigh flat
        body = _progress(A["trunk"], c, f)          # 0 at catch angle, 1 at layback
        i40, i70 = _first_at(legs, 0.4), _first_at(legs, 0.7)
        i30 = _first_at(legs, 0.3)
        s.shoot_deg = float(np.max(A["trunk"][c:c + i30 + 1]) - A["trunk"][c])
        s.arm_bend_at_legs = float(A["elbow"][c] - np.min(A["elbow"][c:c + i70 + 1]))
        s.body_open_at_legs = float(body[i40])
        # ---- recovery sequencing (finish -> next catch)
        knees_up = _progress(A["thigh"], f, n)      # 0 at finish, 1 at next catch
        body_over = _progress(A["trunk"], f, n)     # 0 at layback, 1 at next catch angle
        j30 = _first_at(knees_up, 0.3)
        s.body_set_at_knees = float(body_over[j30])

        # ---- faults
        fl = s.faults
        if s.trunk_catch < 12:                         fl.append("short_catch")
        if s.trunk_catch > 42:                         fl.append("overreach")
        if s.shin_catch is not None and s.shin_catch > 12: fl.append("over_compression")
        if s.trunk_finish < -32:                       fl.append("excess_layback")
        if s.trunk_finish > -3:                        fl.append("no_layback")
        if legs_ok and s.shoot_deg > 5:                fl.append("shooting_slide")
        if arms_ok and legs_ok and s.arm_bend_at_legs > 25: fl.append("early_arms")
        if legs_ok and s.body_open_at_legs > 0.5:      fl.append("early_body")
        if s.rate < 30 and s.ratio < 1.25:             fl.append("rushed_recovery")
        if legs_ok and s.body_set_at_knees < 0.5:      fl.append("late_body_prep")
        strokes.append(s)
    return strokes, h


def summarise(strokes: list[Stroke]) -> dict:
    """Aggregate stroke-level results into a rower-level summary with a 0-100 score."""
    if not strokes:
        return {"n_strokes": 0, "score": None, "issues": []}
    n = len(strokes)
    counts = {}
    for s in strokes:
        for f in s.faults:
            counts[f] = counts.get(f, 0) + 1
    issues = []
    penalty = 0.0
    for f, c in counts.items():
        frac = c / n
        if frac < 0.25:          # ignore occasional one-offs
            continue
        penalty += FAULTS[f]["severity"] * 6 * frac
        issues.append({"code": f, "frac": frac, **FAULTS[f]})
    issues.sort(key=lambda d: -d["severity"] * d["frac"])

    arr = lambda attr: np.array([getattr(s, attr) for s in strokes], dtype=float)
    # stroke-to-stroke repeatability of the body angles at catch and finish
    sd = (np.std(arr("trunk_catch")) + np.std(arr("trunk_finish"))) / 2
    consistency = float(np.clip(100 - 5 * sd, 0, 100))
    penalty += max(0.0, (75 - consistency) / 5)
    return {
        "n_strokes": n,
        "score": int(round(max(0.0, min(100.0, 100 - penalty)))),
        "rate": float(np.median(arr("rate"))),
        "ratio": float(np.median(arr("ratio"))),
        "drive_s": float(np.median(arr("drive_s"))),
        "trunk_catch": float(np.median(arr("trunk_catch"))),
        "trunk_finish": float(np.median(arr("trunk_finish"))),
        "length": float(np.median(arr("length"))),
        "consistency": round(consistency),
        "issues": issues,
        "fault_counts": counts,
    }
