"""Explicit one-boat selection and conservative closed-set association.

Membership is asserted by the operator, not inferred from boat appearance.
Ambiguous, missing or out-of-region targets abort selected analysis; no new
person is recruited to fill a seat. This is not a person re-identification model.
"""
from __future__ import annotations
import math


class SelectionError(ValueError):
    """Safe failure: selected crew cannot be associated unambiguously."""


def validate_selection(value):
    """Return an independent canonical copy; coordinates are fractions [0, 1]."""
    if not isinstance(value, dict) or set(value) != {
        'version', 'roi', 'seeds', 'confirmed_same_boat'
    }:
        raise SelectionError('invalid_selection')
    if type(value['version']) is not int or value['version'] != 1 or value['confirmed_same_boat'] is not True:
        raise SelectionError('invalid_selection')
    def coords(v, count):
        if not isinstance(v, (list, tuple)) or len(v) != count:
            raise SelectionError('invalid_selection')
        if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in v):
            raise SelectionError('invalid_selection')
        return list(map(float, v))
    roi = coords(value['roi'], 4)
    left, top, right, bottom = roi
    if right - left < .01 or bottom - top < .01:
        raise SelectionError('invalid_selection')
    seeds = value['seeds']
    if not isinstance(seeds, (list, tuple)) or len(seeds) != 8:
        raise SelectionError('select_exactly_eight')
    seeds = [coords(p, 2) for p in seeds]
    if any(not (left < x < right and top < y < bottom) for x, y in seeds):
        raise SelectionError('targets_outside_boat_region')
    if any(math.dist(a, b) < .002 for i, a in enumerate(seeds) for b in seeds[:i]):
        raise SelectionError('duplicate_targets')
    return {'version': 1, 'roi': roi, 'seeds': seeds, 'confirmed_same_boat': True}


def locked_tracks(dets, meta, selection):
    """Associate exactly the eight clicked targets, never global top-eight tracks.

    Each initial point must be inside exactly one detection. Subsequent centres
    must lie within a conservative box-relative gate, with no competing matches
    and no large independent departure from the crew's shared movement. A fixed
    crop must contain the crew throughout the clip. Crossings/occlusions can
    cause a safe failure; geometric checks do not prove physical boat identity.
    """
    import numpy as np
    selected = validate_selection(selection)
    scale = np.array([meta['width'], meta['height']], float)
    if not np.isfinite(scale).all() or (scale <= 0).any() or not len(dets):
        raise SelectionError('selection_unavailable')
    roi = np.array(selected['roi']) * np.tile(scale, 2)
    seeds = np.array(selected['seeds']) * scale
    history = {i: {'frames': [], 'boxes': [], 'kpts': []} for i in range(8)}
    previous = None
    for fi, (boxes, kpts) in enumerate(dets):
        boxes, kpts = np.asarray(boxes, float), np.asarray(kpts, float)
        if boxes.ndim != 2 or boxes.shape[1:] != (4,) or kpts.shape != (len(boxes), 17, 3):
            raise SelectionError('selection_unavailable')
        centres = (boxes[:, :2] + boxes[:, 2:]) / 2
        inside = ((centres >= roi[:2]) & (centres <= roi[2:])).all(axis=1)
        valid = (inside & np.isfinite(boxes).all(axis=1)
                 & np.isfinite(kpts).all(axis=(1, 2))
                 & (boxes[:, 2:] > boxes[:, :2]).all(axis=1)
                 & (kpts[:, 5:13, 2].mean(axis=1) >= .25))
        boxes, kpts, centres = boxes[valid], kpts[valid], centres[valid]
        if previous is None:
            matches = (((seeds[:, None, :] >= boxes[None, :, :2])
                        & (seeds[:, None, :] <= boxes[None, :, 2:])).all(axis=2))
        else:
            old_centres = (previous[:, :2] + previous[:, 2:]) / 2
            # Strict enough not to jump one full seat pitch to a neighbouring rower.
            gates = np.maximum((previous[:, 2:] - previous[:, :2]) * .55, 2.0)
            matches = (np.abs(centres[None] - old_centres[:, None]) <= gates[:, None]).all(axis=2)
        if len(boxes) < 8 or not (matches.sum(axis=1) == 1).all():
            raise SelectionError('selected_crew_lost_or_ambiguous')
        indices = matches.argmax(axis=1)
        if len(set(indices)) != 8:
            raise SelectionError('selected_crew_lost_or_ambiguous')
        chosen = boxes[indices]
        if previous is not None:
            movement = (chosen[:, :2] + chosen[:, 2:] - previous[:, :2] - previous[:, 2:]) / 2
            residual = movement - np.median(movement, axis=0)
            if (np.abs(residual) > gates).any():
                raise SelectionError('selected_crew_lost_or_ambiguous')
        for i, j in enumerate(indices):
            history[i]['frames'].append(fi)
            history[i]['boxes'].append(boxes[j].copy())
            history[i]['kpts'].append(kpts[j].copy())
        previous = chosen.copy()
    return {i: {key: np.asarray(v) for key, v in track.items()} for i, track in history.items()}
