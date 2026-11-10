"""Stroke segmentation, per-stroke technique metrics, and fault detection."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.signal import find_peaks

from .kinematics import Kinematics, smooth
from . import measurement

VERSION = "fractional-phase-clock-v1"

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
        cue="Stop the slide when the shins are vertical — going further makes the leg power harder to connect.",
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
    observed_frames: int = 0
    gap_frames: int = 0
    finish_t: float = 0.0   # sub-frame finish time (frames), same clock as catch_t

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
    """Rhythm strength on the source-frame clock, with missing-pair support.

    Missing samples are excluded from lag products, never concatenated away.
    Pair-count correction avoids penalizing random observation gaps; complete
    finite inputs retain the original autocorrelation and lag taper exactly.
    """
    values = np.asarray(sig, float)
    if values.ndim != 1 or not np.isfinite(fps) or fps <= 0:
        raise ValueError('invalid rhythm signal or frame rate')
    if not (np.isfinite([min_rate, max_rate]).all() and 0 < min_rate < max_rate):
        raise ValueError('invalid rhythm rate bounds')
    valid = np.isfinite(values)
    if valid.sum() < fps * 4:
        return 0.0
    first, last = np.flatnonzero(valid)[[0, -1]]
    values, valid = values[first:last+1], valid[first:last+1]
    n = len(values)
    x = np.where(valid, values - values[valid].mean(), 0.)
    energy = float(np.dot(x, x))
    if np.std(values[valid]) < 1e-9 or energy <= 0:
        return 0.0
    lo, hi = max(1, int(fps * 60 / max_rate)), min(n-1, int(fps * 60 / min_rate))
    best = 0.
    for lag in range(lo, hi):
        pairs = int(np.count_nonzero(valid[:-lag] & valid[lag:]))
        if pairs < max(5, fps, .25*(n-lag)):
            continue
        numerator = float(np.dot(x[:-lag], x[lag:]))
        correction = valid.sum() * (n-lag) / (n*pairs)
        best = max(best, numerator/energy*correction)
    return float(np.clip(best, 0., 1.))


def find_strokes(k: Kinematics, min_rate=12, max_rate=50):
    """Return list of (catch, finish, next_catch) frame indices."""
    # Kinematics is canonical: do not re-filter differently for scoring/plots.
    h = k.handle.copy()
    if not k.visible.any():
        return [], h, {}
    cues, weights = [], []
    names = ['handle', 'thigh' if k.reliable.get('knee') else 'trunk']
    for name in names:
        values = h if name == 'handle' else k.angles[name]
        if not measurement.supported(k, name, values):
            continue
        mask = measurement.observed_mask(k, name) & np.isfinite(values)
        lo, hi = np.percentile(values[mask], [5, 95])
        normalized = (values-lo)/(hi-lo)
        strength = periodicity(np.where(mask, normalized, np.nan), k.fps, min_rate, max_rate)
        if strength < .15:
            continue
        cues.append(normalized)
        weights.append(strength ** 2)
    if not cues:
        return [], h, {}
    # Quality-weighted motion evidence; no unconditional preference for knees.
    values = np.asarray(cues)
    valid = np.isfinite(values)
    weights = np.asarray(weights)[:, None] * valid
    denom = weights.sum(axis=0)
    c_sig = np.divide((np.where(valid, values, 0) * weights).sum(axis=0), denom,
                      out=np.full(len(h), np.nan), where=denom > 0)
    min_dist = int(k.fps * 60 / max_rate * 0.8)
    finite = np.isfinite(c_sig)
    edges = np.diff(np.r_[False, finite, False].astype(int))
    candidates = []
    for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        peaks, _ = find_peaks(c_sig[start:stop], prominence=.3, distance=max(1, min_dist))
        candidates.extend((peaks+start).tolist())
    catches = np.asarray(candidates, dtype=int)
    out = []
    for c0, c1 in zip(catches[:-1], catches[1:]):
        period_s = (c1 - c0) / k.fps
        if not (60 / max_rate <= period_s <= 60 / min_rate):
            continue
        if (k.visible[c0:c1 + 1].mean() < .9
                or not np.isfinite(c_sig[c0:c1+1]).all()
                or not np.isfinite(h[c0:c1+1]).all()):
            continue
        f = c0 + int(np.argmin(c_sig[c0:c1 + 1]))
        if f in (c0, c1) or not k.visible[[c0, f, c1]].all():
            continue
        # the drive is ~25-60% of the stroke cycle; outside that the segmentation is unreliable
        if not (0.2 <= (f - c0) / (c1 - c0) <= 0.65):
            continue
        out.append((int(c0), int(f), int(c1)))
    refined = {int(c): _refine_peak(c_sig, int(c)) for c in catches}
    refined.update({int(f): _refine_peak(-c_sig, int(f)) for _, f, _ in out})
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


def analyse(k: Kinematics, *, workers: int = 1, max_gap_frames: int | None = None,
            min_observed_fraction: float = 0.9):
    """Segment first, then measure independent complete cycles in ordered work.

    Short-gap estimates are explicitly counted; missing samples remain missing.
    Parallelism applies to cycle measurements, not identity tracking or rendering.
    """
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must be an integer from 1 to 4')
    if max_gap_frames is not None and (type(max_gap_frames) is not int or max_gap_frames < 0):
        raise ValueError('invalid gap bound')
    if not 0.9 <= min_observed_fraction <= 1:
        raise ValueError('invalid observed fraction')
    segs, h, refined = find_strokes(k)
    if max_gap_frames is not None:
        def acceptable(segment):
            c, f, n = segment
            visible = k.visible[c:n+1]
            # Critical phase points and their neighbours must be observations.
            for landmark in (c, f, n):
                if not k.visible[max(c,landmark-1):min(n+1,landmark+2)].all():
                    return False
            edges = np.diff(np.r_[False, ~visible, False].astype(int))
            lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
            return visible.mean() >= min_observed_fraction and (not len(lengths) or lengths.max() <= max_gap_frames)
        segs = [segment for segment in segs if acceptable(segment)]
    A = k.angles
    # Only judge a body part we can actually see well
    if segs:
        travel = np.median([h[c] - h[f] for c, f, _ in segs])
    else:
        travel = 0
    arms_ok = travel >= 1.0 and k.reliable.get("elbow", False)
    shins_ok = "shin" in A and float(np.mean(k.conf["ankle"] >= 0.5)) >= 0.8
    legs_ok = k.reliable.get("knee", False)
    def measure(item):
        i, (c, f, n) = item
        ct, ft, nt = (refined.get(index, float(index)) for index in (c, f, n))
        # Discrete landmarks still select measured poses. Durations and rate
        # must use the same fractional event clock as crew synchronization.
        if not (np.isfinite([ct, ft, nt]).all() and c-.5 <= ct <= c+.5
                and f-.5 <= ft <= f+.5 and n-.5 <= nt <= n+.5 and ct < ft < nt):
            ct, ft, nt = float(c), float(f), float(n)
        drive = (ft - ct) / k.fps
        rec = (nt - ft) / k.fps
        s = Stroke(
            idx=i, catch=c, catch_t=ct, finish=f, finish_t=ft, next_catch=n,
            rate=60.0 / ((nt - ct) / k.fps), drive_s=drive, recovery_s=rec, ratio=rec / max(drive, 1e-6),
            length=float(h[c] - h[f]),
            trunk_catch=float(A["trunk"][c]), trunk_finish=float(A["trunk"][f]),
            thigh_catch=float(A["thigh"][c]) if np.isfinite(A["thigh"][c]) else None,
            elbow_catch=float(A["elbow"][c]) if np.isfinite(A["elbow"][c]) else None,
            shin_catch=(float(A["shin"][c]) if shins_ok
                        and measurement.observed_mask(k, 'shin')[c]
                        and np.isfinite(A['shin'][c]) else None),
            next_catch_t=nt,
            observed_frames=int(k.visible[c:n+1].sum()),
            gap_frames=int((~k.visible[c:n+1]).sum()),
        )
        legs_valid = legs_ok and measurement.segment_supported(k, 'thigh', c, n+1)
        body_valid = measurement.segment_supported(k, 'trunk', c, n+1)
        arms_valid = arms_ok and measurement.segment_supported(k, 'elbow', c, n+1)
        # ---- drive sequencing (catch -> finish)
        legs = _progress(A["thigh"], c, f)          # 0 at catch, 1 when thigh flat
        body = _progress(A["trunk"], c, f)          # 0 at catch, 1 at layback
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

        if not legs_valid or not body_valid:
            s.shoot_deg = s.body_open_at_legs = s.body_set_at_knees = None
        if not legs_valid or not arms_valid:
            s.arm_bend_at_legs = None
        # ---- faults
        fl = s.faults
        if s.trunk_catch < 12:                         fl.append("short_catch")
        if s.trunk_catch > 42:                         fl.append("overreach")
        if s.shin_catch is not None and s.shin_catch > 12: fl.append("over_compression")
        if s.trunk_finish < -32:                       fl.append("excess_layback")
        if s.trunk_finish > -3:                        fl.append("no_layback")
        if legs_valid and body_valid and s.shoot_deg is not None and s.shoot_deg > 5:                fl.append("shooting_slide")
        if arms_valid and legs_valid and s.arm_bend_at_legs is not None and s.arm_bend_at_legs > 25: fl.append("early_arms")
        if legs_valid and body_valid and s.body_open_at_legs > 0.5:      fl.append("early_body")
        if s.rate < 30 and s.ratio < 1.25:             fl.append("rushed_recovery")
        if legs_valid and body_valid and s.body_set_at_knees < 0.5:      fl.append("late_body_prep")
        return s
    if workers == 1 or len(segs) < 2:
        measured = [measure(item) for item in enumerate(segs)]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(segs)),
                                thread_name_prefix='stroke-measure') as pool:
            measured = list(pool.map(measure, enumerate(segs)))
    return measured, h


def summarise(strokes: list[Stroke]) -> dict:
    """Aggregate stroke-level results into a rower-level summary with a 0-100 score."""
    assessment = {"minimum_strokes": 5, "usable_strokes": len(strokes),
                  "state": "short_assessment_ready" if len(strokes) >= 5 else "preliminary",
                  "coach_validated": False}
    if not strokes:
        return {"n_strokes": 0, "score": None, "issues": [], "assessment": assessment}
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
        "consistency": round(consistency) if n >= 2 else None,
        "assessment": assessment,
        "issues": issues,
        "fault_counts": counts,
    }
