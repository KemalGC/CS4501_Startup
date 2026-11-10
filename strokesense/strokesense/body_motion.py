"""Conservative temporal conditioning of an observed anatomical joint chain.

Reject isolated, joint-specific detector jumps without mistaking shared camera
motion for body movement. A rejected point is missing evidence, not a corrected
observation. No limb-length or ideal rowing-form constraint is imposed.
"""
import numpy as np
from scipy.signal import savgol_filter

VERSION = 'camera-relative-joint-quality-v1'


def isolated_joint_spikes(points, valid, torso_scale):
    """Return an (N,J) mask of isolated implausible reversals.

    Five-frame interpolation residuals remove smooth acceleration. Common
    residual/velocity across at least three joints removes camera translation.
    Both adjacent differential steps must reverse and exceed a scale/noise gate.
    Sustained motion, boundaries, and gaps are deliberately not corrected.
    """
    points = np.asarray(points, float)
    valid = np.asarray(valid, bool)
    n, joints = valid.shape
    rejected = np.zeros((n, joints), bool)
    if n < 5:
        return rejected
    support = np.logical_and.reduce([valid[i:n-4+i] for i in range(5)])
    mid = points[2:-2]
    residual = mid - (2/3 * (points[1:-3] + points[3:-1])
                      - 1/6 * (points[:-4] + points[4:]))
    before, after = mid-points[1:-3], points[3:-1]-mid
    enough = support.sum(1) >= 3
    for fi in np.flatnonzero(enough):
        for values in (residual, before, after):
            values[fi] -= np.median(values[fi, support[fi]], axis=0)
    support &= enough[:, None]
    for j in range(joints):
        use = support[:, j]
        if use.sum() < 7:
            continue
        r = residual[use, j]
        sigma = 1.4826 * np.median(np.abs(r - np.median(r, axis=0)), axis=0)
        threshold = max(3., .4 * torso_scale, 6. * float(np.linalg.norm(sigma)))
        a, b = before[:, j], after[:, j]
        la, lb = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
        reverse = np.sum(a*b, axis=1) < -.5 * la * lb
        rejected[2:-2, j] = (use & reverse
            & (np.minimum(la, lb) > .75*threshold)
            & (np.linalg.norm(residual[:, j], axis=1) > threshold))
    # Alternating/clustered disagreement does not identify which observation is
    # wrong. Preserve it rather than rejecting a correct point between bad ones.
    for j in range(joints):
        count = np.convolve(rejected[:, j].astype(int), np.ones(5, int), mode='same')
        rejected[:, j] &= count == 1
    return rejected


def confidence_smooth(values, confidence, fps, seconds=.15):
    """Centered confidence-weighted quadratic smoothing, independently per run.

    Equal-confidence observations reproduce the existing Savitzky–Golay fit.
    Centered fits avoid causal lag. No fit spans a missing interval or creates
    new observations. Short runs retain their supplied values.
    """
    values = np.asarray(values, float)
    confidence = np.asarray(confidence, float)
    result = values.copy()
    valid = np.isfinite(values).all(1)
    result[~valid] = np.nan
    window = max(5, int(round(fps*seconds)) | 1)
    edges = np.diff(np.r_[False, valid, False].astype(int))
    for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if stop-start <= window:
            continue
        weights = np.clip(confidence[start:stop], .05, 1.)
        if np.ptp(weights) < 1e-12:
            result[start:stop] = savgol_filter(values[start:stop], window, 2, axis=0)
            continue
        for i in range(start, stop):
            left = max(start, min(i-window//2, stop-window))
            ids = np.arange(left, left+window)
            x = (ids-i).astype(float)
            design = np.stack([np.ones(window), x, x*x], axis=1)
            weight = np.clip(confidence[ids], .05, 1.)
            coefficients = np.linalg.lstsq(design*weight[:, None],
                                           values[ids]*weight[:, None], rcond=None)[0]
            result[i] = coefficients[0]
    return result
