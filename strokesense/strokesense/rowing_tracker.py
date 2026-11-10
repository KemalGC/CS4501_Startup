"""Ordered, camera-motion-aware association for a single rowing shell.

The model keeps seat order, estimates shared translation/zoom, and allows both
missing seats and extra detections. Predictions support association only: every
returned index points to an actual detector observation.
"""
from __future__ import annotations
import numpy as np

VERSION = 'ordered-crew-motion-v1'


def centres(boxes, keypoints):
    """Confidence-weighted hips avoid arms changing the centre of a person box."""
    hips = keypoints[:, [11, 12]]
    weights = hips[:, :, 2] * (hips[:, :, 2] >= .25)
    total = weights.sum(1)
    fallback = (boxes[:, :2] + boxes[:, 2:]) / 2
    return np.where((total > 0)[:, None],
                    (hips[:, :, :2] * weights[:, :, None]).sum(1)
                    / np.maximum(total[:, None], 1e-9), fallback)


def ordered_assignment(cost, missing=.55):
    """Minimum-cost monotonic matching, with explicit misses and free clutter.

    Unlike assignment followed by thresholding, an ineligible observation can
    never consume a detection needed by a different seat.
    """
    n, m = cost.shape
    dp = np.full((n + 1, m + 1), np.inf)
    action = np.zeros((n + 1, m + 1), np.int8)
    dp[0] = 0
    dp[:, 0] = np.arange(n + 1) * missing
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = (dp[i-1, j] + missing, dp[i, j-1], dp[i-1, j-1] + cost[i-1, j-1])
            a = int(np.argmin(options))
            dp[i, j], action[i, j] = options[a], a
    pairs = []
    i, j = n, m
    while i and j:
        a = action[i, j]
        if a == 2:
            pairs.append((i-1, j-1)); i -= 1; j -= 1
        elif a == 1:
            j -= 1
        else:
            i -= 1
    return pairs[::-1], float(dp[n, m])


def local_pitch(points, fallback):
    if len(points) < 2:
        return np.full(len(points), max(fallback, 2.))
    gaps = np.maximum(np.diff(points[:, 0]), 2.)
    return np.r_[gaps[0], np.minimum(gaps[:-1], gaps[1:]), gaps[-1]]


class SeatTracker:
    def __init__(self, boxes, keypoints, fps):
        self.slots = centres(boxes, keypoints).copy()
        self.sizes = (boxes[:, 2:] - boxes[:, :2]).copy()
        self.velocity = np.zeros_like(self.slots)
        self.missed = np.zeros(len(boxes), int)
        self.limit = max(1, int(.75 * fps))
        self.unsupported = 0
        self.retired = False

    def update(self, boxes, keypoints):
        dc = centres(boxes, keypoints)
        order = np.argsort(dc[:, 0], kind='stable')
        dc, sizes = dc[order], (boxes[:, 2:] - boxes[:, :2])[order]
        pitch = local_pitch(self.slots, np.median(self.sizes[:, 0]))
        predicted = self.slots + self.velocity
        if self.unsupported >= self.limit:
            self.retired = True
        live = np.full(len(self.slots), not self.retired)
        if not len(dc) or not live.any():
            self.slots = predicted
            self.velocity *= .8
            self.missed += 1
            self.unsupported += 1
            return []
        # Use nearby correspondences to estimate the shared motion. Candidate
        # shifts are bounded below a seat pitch to prevent periodic aliasing.
        residual = dc[None] - predicted[:, None]
        plausible = ((np.abs(residual[..., 0]) < .7 * pitch[:, None])
                     & (np.abs(residual[..., 1]) < .5 * self.sizes[:, None, 1])
                     & live[:, None])
        candidates = [np.zeros(2)]
        candidates.extend(residual[plausible])
        best = None
        for shift in candidates:
            delta = predicted[:, None] + shift - dc[None]
            dist = np.linalg.norm(delta / pitch[:, None, None], axis=2)
            nearest = dist.argmin(1)
            inliers = live & (dist[np.arange(len(dist)), nearest] < .25)
            # A lone observation cannot move the entire crew.
            if np.linalg.norm(shift) and inliers.sum() < min(3, len(self.slots)):
                continue
            score = np.minimum(dist.min(1)[live], .45).sum() + .12 * np.linalg.norm(shift) / np.median(pitch)
            if best is None or score < best[0]:
                best = (score, shift, inliers, nearest)
        _, shift, inliers, nearest = best
        predicted += shift
        # Robust affine correction models changes in zoom and viewing angle.
        # Only well-supported correspondences contribute; retain local spacing.
        ids = np.flatnonzero(inliers)
        if len(ids) >= 3 and len(set(nearest[ids])) == len(ids):
            x = predicted[ids, 0]
            dx = x[:, None] - x[None]
            pairs = np.triu(np.abs(dx) > np.median(pitch), 1)
            if pairs.any():
                slopes = (dc[nearest[ids], 0][:, None] - dc[nearest[ids], 0][None]) / np.where(dx != 0, dx, 1)
                scale = float(np.clip(np.median(slopes[pairs]), .94, 1.06))
                origin = np.median(x)
                predicted[:, 0] = origin + scale * (predicted[:, 0] - origin)
                predicted += np.median(dc[nearest[ids]] - predicted[ids], axis=0)
        pitch = local_pitch(predicted, np.median(self.sizes[:, 0]))
        delta = predicted[:, None] - dc[None]
        # Vertical gates use person height, while horizontal gates use each
        # seat's local pitch (perspective can compress the far end of a shell).
        cost = np.sqrt((delta[..., 0] / pitch[:, None])**2
                       + (delta[..., 1] / np.maximum(self.sizes[:, None, 1], 2))**2)
        ratio = sizes[None] / np.maximum(self.sizes[:, None], 1)
        eligible = ((np.abs(delta[..., 0]) < .45 * pitch[:, None])
                    & (np.abs(delta[..., 1]) < .5 * self.sizes[:, None, 1])
                    & ((ratio > .4) & (ratio < 2.5)).all(2) & live[:, None])
        cost[~eligible] = np.inf
        accepted, optimum = ordered_assignment(cost)
        # Reject near-equivalent competing detections rather than arbitrarily
        # choosing one. This is independent of raw detector ordering.
        certain = []
        for si, di in accepted:
            alternate = cost.copy(); alternate[si, di] = np.inf
            _, alt_cost = ordered_assignment(alternate)
            if alt_cost - optimum >= .06:
                certain.append((si, di))
        old = self.slots.copy()
        self.slots = predicted
        self.missed += 1
        if len(certain) >= min(3, len(self.slots)):
            common = np.median([dc[j] - old[i] for i, j in certain], axis=0)
            self.velocity = .5 * self.velocity + .5 * common
            self.unsupported = 0
        else:
            self.velocity *= .8
            self.unsupported += 1
            certain = [(i, j) for i, j in certain if self.missed[i] <= self.limit]
        for i, j in certain:
            self.slots[i] = dc[j]
            self.sizes[i] = .8 * self.sizes[i] + .2 * sizes[j]
            self.missed[i] = 0
        return [(i, int(order[j])) for i, j in certain]
