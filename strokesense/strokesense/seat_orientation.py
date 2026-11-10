"""Conservative eight-seat ordering for side-on rowing footage.

Track slot IDs are visual left-to-right IDs, not physical seat identities.
Rowers face the stern, opposite boat travel. Only make a full bow-to-stroke
assignment when observed pose direction and stable spatial order agree.
"""
from __future__ import annotations

import numpy as np


def _uncertain(reason: str, confidence=None):
    return {
        "status": "uncertain",
        "travel_direction": None,
        "confidence": confidence,
        "assignments": {},
        "reason": reason,
        "source": None,
    }


def infer_dominant_seats(tracks: dict, *, crew_facing: int, n_seats: int) -> dict:
    """Estimate physical positions only for a supported eight-person side view.

    This is an orientation *heuristic*, not a calibrated probability of correct
    seat identification. Camera motion/translation is never taken as travel
    evidence, because a panning camera could reverse that inference.
    """
    if n_seats != 8 or not isinstance(tracks, dict) or set(tracks) != set(range(8)):
        return _uncertain("A complete eight-person crew was not reliably tracked.")
    if crew_facing not in (-1, 1):
        return _uncertain("Boat-facing direction was unavailable.")

    votes = []
    frame_centres = []
    for slot in range(8):
        item = tracks[slot]
        if not isinstance(item, dict):
            return _uncertain("Tracking data did not support seat ordering.")
        try:
            points = np.asarray(item["kpts"], dtype=float)
            boxes = np.asarray(item["boxes"], dtype=float)
            frames = np.asarray(item["frames"], dtype=float)
        except (KeyError, ValueError, TypeError):
            return _uncertain("Tracking data did not support seat ordering.")
        if (points.ndim != 3 or points.shape[1:] != (17, 3)
                or boxes.ndim != 2 or boxes.shape[1] != 4
                or frames.ndim != 1 or len(points) != len(boxes) or len(boxes) != len(frames)
                or not 8 <= len(frames) <= 20_000 or not np.isfinite(frames).all()):
            return _uncertain("Insufficient consistent frames for an eight-seat order.")

        widths = boxes[:, 2] - boxes[:, 0]
        valid_box = np.isfinite(boxes).all(axis=1) & (widths >= 12)
        widths = np.maximum(widths, 1)
        pair_dx = np.zeros((len(frames), 2), dtype=float)
        valid_pair = np.zeros((len(frames), 2), dtype=bool)
        for side, (hip, knee) in enumerate(((11, 13), (12, 14))):
            h, k = points[:, hip], points[:, knee]
            good = (valid_box & np.isfinite(h).all(axis=1) & np.isfinite(k).all(axis=1)
                    & (h[:, 2] >= .35) & (k[:, 2] >= .35))
            dx = (k[:, 0] - h[:, 0]) / widths
            good &= np.abs(dx) >= .055  # Frontal and uncertain limb poses abstain.
            valid_pair[:, side] = good
            pair_dx[:, side] = np.where(good, dx, 0)
        pair_counts = valid_pair.sum(axis=1)
        mean_dx = np.divide(pair_dx.sum(axis=1), np.maximum(pair_counts, 1))
        useful = (pair_counts > 0) & (np.abs(mean_dx) >= .055)
        signs = np.sign(mean_dx[useful])
        if len(signs) >= 10:
            consistency = float(abs(np.mean(signs)))
            if consistency >= .65:
                votes.append((int(np.sign(np.mean(signs))), len(signs), consistency))

        # Slots are expected to remain left-to-right; verify this independently.
        centres = (boxes[:, 0] + boxes[:, 2]) / 2
        frame_centres.append({
            int(frame): float(x)
            for frame, x, good in zip(frames, centres, valid_box)
            if good and np.isfinite(frame) and float(frame).is_integer()
        })

    if len(votes) < 6:
        return _uncertain("Too few rowers have reliable side-on facing evidence.")
    signs = [direction for direction, _, _ in votes]
    face_sign = 1 if signs.count(1) > signs.count(-1) else -1
    agreement = signs.count(face_sign) / len(signs)
    if agreement < .85 or face_sign != int(crew_facing):
        return _uncertain("Rower-facing evidence does not consistently establish boat direction.",
                          round(float(agreement), 2))

    pair_order = []
    for slot in range(7):
        left, right = frame_centres[slot], frame_centres[slot + 1]
        common = left.keys() & right.keys()
        if len(common) < 5:
            return _uncertain("Adjacent rower positions do not overlap enough to confirm order.")
        pair_order.append(sum(left[f] < right[f] for f in common) / len(common))
    order_agreement = float(np.mean(pair_order))
    if min(pair_order) < .85 or order_agreement < .9:
        return _uncertain("Tracked rowers did not maintain a stable left-to-right seat order.")

    rower_support = len(votes) / 8
    frame_support = min(1., float(np.median([count for _, count, _ in votes])) / 40.)
    evidence_strength = round(
        float(.45 * agreement + .25 * rower_support +
              .15 * frame_support + .15 * order_agreement), 2)
    if evidence_strength < .82:
        return _uncertain("Pose evidence is not strong enough to assign physical seats.",
                          evidence_strength)

    # Facing right means stern right and bow/travel left. The inverse holds
    # for facing left. Never infer physical positions from numeric track IDs alone.
    assignments = {}
    for slot in range(8):
        bow_index = slot if face_sign > 0 else 7 - slot
        label = ("Bow seat" if bow_index == 0 else
                 "Stroke seat" if bow_index == 7 else f"Seat {bow_index + 1}")
        assignments[f"R{slot + 1}"] = label
    return {
        "status": "auto",
        "travel_direction": "left" if face_sign > 0 else "right",
        "confidence": evidence_strength,
        "assignments": assignments,
        "reason": "Estimated from consistent rower-facing poses and stable spatial order; coach verification recommended.",
        "source": "pose_orientation_and_spatial_order",
    }
