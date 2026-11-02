"""Turn raw 2D keypoints into clean, rower-centric kinematic signals.

Keypoints follow the COCO-17 layout produced by YOLO pose models:
 0 nose, 1/2 eyes, 3/4 ears, 5/6 shoulders, 7/8 elbows, 9/10 wrists,
 11/12 hips, 13/14 knees, 15/16 ankles   (odd = left, even = right)

Coordinate frame used everywhere after this module:
  u = "forward" distance, toward the rower's feet (the stern), in torso lengths
  v = "up" distance, in torso lengths
  origin = the hip on every frame, so boat motion and camera panning cancel out.

On the water the feet are usually hidden by the hull, so nothing essential depends
on the ankles: leg drive is measured from the thigh angle instead of the knee angle.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

LEFT = {"shoulder": 5, "elbow": 7, "wrist": 9, "hip": 11, "knee": 13, "ankle": 15}
RIGHT = {"shoulder": 6, "elbow": 8, "wrist": 10, "hip": 12, "knee": 14, "ankle": 16}
JOINTS = ["shoulder", "elbow", "wrist", "hip", "knee", "ankle"]


@dataclass
class Kinematics:
    fps: float
    side: str                      # body side facing the camera: "left" / "right"
    facing: int                    # +1 the rower's feet point to image-right, -1 to image-left
    scale_px: float                # torso length (hip -> shoulder) in pixels
    px: dict = field(default_factory=dict)        # joint -> (N,2) smoothed pixel coords (for drawing)
    uv: dict = field(default_factory=dict)        # joint -> (N,2) rower-centric coords
    conf: dict = field(default_factory=dict)      # joint -> (N,) detection confidence
    reliable: dict = field(default_factory=dict)  # joint -> bool (seen well enough to use)
    visible: np.ndarray | None = None             # (N,) frame has a usable upper body
    angles: dict = field(default_factory=dict)    # name -> (N,) degrees

    observed: dict = field(default_factory=dict)   # directly detected at the chosen confidence
    estimated: dict = field(default_factory=dict)  # bounded internal interpolation, never observations

    @property
    def n(self) -> int:
        return len(self.visible)

    @property
    def handle(self) -> np.ndarray:
        """Forward reach of the hands relative to the hips: max at the catch, min at the finish."""
        return self.uv["wrist"][:, 0]


def _interp_gaps(arr: np.ndarray, good: np.ndarray, max_gap: int = 0) -> np.ndarray:
    """Estimate only enclosed short gaps; retain NaN at long gaps and edges."""
    out = np.asarray(arr, float).copy()
    out[~good] = np.nan
    edges = np.diff(np.r_[False, ~good, False].astype(int))
    for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if start > 0 and stop < len(out) and stop - start <= max_gap:
            for d in range(out.shape[1]):
                out[start:stop, d] = np.linspace(out[start-1, d], out[stop, d], stop-start+2)[1:-1]
    return out


def smooth(arr: np.ndarray, fps: float, seconds: float = 0.2) -> np.ndarray:
    """Smooth observed runs independently; never bridge missing measurements.

    Finite inputs retain the original filter and window behavior. Each channel
    has its own missing mask; short spans remain unchanged. NaN and infinity
    mark unavailable observations, not zeros or interpolated measurements.
    """
    values = np.asarray(arr, dtype=float)
    win = max(5, int(round(fps * seconds)) | 1)
    if np.isfinite(values).all():
        if len(values) <= win:
            return values.copy()
        return savgol_filter(values, win, 2, axis=0)
    result = values.copy()
    result[~np.isfinite(result)] = np.nan
    channels = result.reshape(len(result), -1)
    for series in channels.T:
        valid = np.isfinite(series)
        edges = np.diff(np.r_[False, valid, False].astype(int))
        for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            if stop - start > win:
                series[start:stop] = savgol_filter(series[start:stop], win, 2)
    return result


def angle_at(a, b, c) -> np.ndarray:
    """Interior angle ABC in degrees for (N,2) arrays."""
    ba, bc = a - b, c - b
    cos = (ba * bc).sum(1) / (np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def tilt_from_vertical(lower, upper) -> np.ndarray:
    """Angle of segment lower->upper from vertical; + means the top leans toward the feet."""
    d = upper - lower
    return np.degrees(np.arctan2(d[:, 0], d[:, 1]))


def build(keypoints: np.ndarray, fps: float, min_conf: float = 0.35) -> Kinematics:
    """keypoints: (N, 17, 3) array of x, y, confidence in pixels (conf 0 = not detected)."""
    kp = np.asarray(keypoints, dtype=float)

    if kp.ndim != 3 or kp.shape[1:] != (17, 3) or not len(kp):
        raise ValueError('keypoints must have shape (N, 17, 3)')
    if not np.isfinite(fps) or fps <= 0 or not 0 < min_conf <= 1:
        raise ValueError('invalid kinematic settings')
    # Select one anatomical chain for this track. Never splice opposite-side
    # joints into it on individual frames; missing near-side data remains missing.
    confidence = np.where(np.isfinite(kp[:, :, 2]), kp[:, :, 2], 0.)
    lc = confidence[:, list(LEFT.values())].mean()
    rc = confidence[:, list(RIGHT.values())].mean()
    near, side = (LEFT, 'left') if lc >= rc else (RIGHT, 'right')
    px, conf, reliable, observed, estimated = {}, {}, {}, {}, {}
    for j in JOINTS:
        a = kp[:, near[j]]
        c = confidence[:, near[j]].copy()
        good = (c >= min_conf) & np.isfinite(a[:, :2]).all(axis=1)
        xy = _interp_gaps(a[:, :2], good, int(np.floor(fps * .2)))
        observed[j] = good
        estimated[j] = ~good & np.isfinite(xy).all(axis=1)
        reliable[j] = bool(good.mean() >= .5)
        px[j] = smooth(xy, fps, .15)
        conf[j] = c
    core = ['shoulder', 'hip', 'wrist']
    visible = np.all([observed[j] for j in core], axis=0)
    torso = np.linalg.norm(px['shoulder'] - px['hip'], axis=1)
    valid_scale = torso[np.isfinite(torso) & (torso > 1e-6)]
    scale = float(np.median(valid_scale)) if len(valid_scale) else 1.0
    ref = 'knee' if reliable['knee'] else 'wrist'
    facing_values = px[ref][:, 0] - px['hip'][:, 0]
    facing_values = facing_values[np.isfinite(facing_values)]
    facing = 1 if not len(facing_values) or np.median(facing_values) >= 0 else -1

    # 4) Rower-centric coordinates, origin at the hip each frame
    uv = {}
    for j in JOINTS:
        d = px[j] - px["hip"]
        uv[j] = np.stack([d[:, 0] * facing, -d[:, 1]], axis=1) / scale

    trunk = tilt_from_vertical(uv["hip"], uv["shoulder"])
    # Physical projected angles are not detrended: camera motion and real posture
    # cannot be distinguished from a low-frequency angle trend alone.
    angles = {
        "trunk": trunk,                                              # + body over, - layback
        "elbow": angle_at(uv["shoulder"], uv["elbow"], uv["wrist"]),  # 180 = arms straight
        # thigh elevation above horizontal: high at the catch (knees up), ~flat at the finish
        "thigh": np.degrees(np.arctan2(uv["knee"][:, 1], np.abs(uv["knee"][:, 0]) + 1e-9)),
    }
    if reliable["ankle"] and reliable["knee"]:
        angles["knee"] = angle_at(uv["hip"], uv["knee"], uv["ankle"])
        angles["shin"] = tilt_from_vertical(uv["ankle"], uv["knee"])   # + knees past the feet

    return Kinematics(fps=fps, side=side, facing=facing, scale_px=scale, px=px, uv=uv,
                      conf=conf, reliable=reliable, visible=visible, angles=angles,
                      observed=observed, estimated=estimated)


def sliced(k: Kinematics, start: int, stop: int) -> Kinematics:
    """Slice canonical signals without selecting a new body side or filtering twice."""
    from dataclasses import replace
    mappings = {name: {joint: values[start:stop].copy() for joint, values in getattr(k, name).items()}
                for name in ('px', 'uv', 'conf', 'angles', 'observed', 'estimated')}
    return replace(k, visible=k.visible[start:stop].copy(), reliable=k.reliable.copy(), **mappings)
