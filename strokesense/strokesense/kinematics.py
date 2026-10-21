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

    @property
    def n(self) -> int:
        return len(self.visible)

    @property
    def handle(self) -> np.ndarray:
        """Forward reach of the hands relative to the hips: max at the catch, min at the finish."""
        return self.uv["wrist"][:, 0]


def _interp_gaps(arr: np.ndarray, good: np.ndarray) -> np.ndarray:
    out = arr.copy()
    idx = np.arange(len(arr))
    if good.sum() < 2:
        return out
    for d in range(arr.shape[1]):
        out[~good, d] = np.interp(idx[~good], idx[good], arr[good, d])
    return out


def smooth(arr: np.ndarray, fps: float, seconds: float = 0.2) -> np.ndarray:
    win = max(5, int(round(fps * seconds)) | 1)  # odd window
    if len(arr) <= win:
        return arr
    return savgol_filter(arr, win, 2, axis=0)


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

    # 1) Which side of the body faces the camera? Use the side the model is more sure of.
    lc = kp[:, list(LEFT.values()), 2].mean()
    rc = kp[:, list(RIGHT.values()), 2].mean()
    near, far, side = (LEFT, RIGHT, "left") if lc >= rc else (RIGHT, LEFT, "right")

    px, conf, reliable = {}, {}, {}
    for j in JOINTS:
        a, b = kp[:, near[j]], kp[:, far[j]]
        use_far = (a[:, 2] < min_conf) & (b[:, 2] > a[:, 2])       # occluded near side -> use far side
        xy = np.where(use_far[:, None], b[:, :2], a[:, :2])
        c = np.where(use_far, b[:, 2], a[:, 2])
        good = c >= min_conf
        reliable[j] = bool(good.mean() >= 0.5)
        px[j] = smooth(_interp_gaps(xy, good), fps, 0.15)
        conf[j] = c

    core = ["shoulder", "hip", "wrist"]
    visible = np.all([conf[j] >= min_conf * 0.6 for j in core], axis=0)

    # 2) Body scale: median torso length in pixels
    torso = np.linalg.norm(px["shoulder"] - px["hip"], axis=1)
    scale = float(np.median(torso[visible])) if visible.any() else float(np.median(torso))
    scale = scale or 1.0

    # 3) Facing direction: seated rowers always have knees forward of hips (toward the stern)
    ref = "knee" if reliable["knee"] else "wrist"
    facing = 1 if np.median(px[ref][:, 0] - px["hip"][:, 0]) >= 0 else -1

    # 4) Rower-centric coordinates, origin at the hip each frame
    uv = {}
    for j in JOINTS:
        d = px[j] - px["hip"]
        uv[j] = np.stack([d[:, 0] * facing, -d[:, 1]], axis=1) / scale

    trunk = tilt_from_vertical(uv["hip"], uv["shoulder"])
    # Remove slow drift (the launch changing its viewing angle, the boat pitching): technique
    # lives within a stroke, so anything slower than ~3 strokes is treated as camera, not rower.
    win = int(fps * 5)
    if len(trunk) > 2 * win and visible.sum() > win:
        from scipy.ndimage import median_filter
        filled = np.where(visible, trunk, np.median(trunk[visible]))
        trend = median_filter(filled, size=win, mode="nearest")
        trunk = trunk - trend + np.median(trend[visible])
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
                      conf=conf, reliable=reliable, visible=visible, angles=angles)
