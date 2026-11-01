"""Explicit one-boat selection and conservative closed-set association.

Membership is asserted by the operator, not inferred from boat appearance.
Initial targets must be unambiguous. Later missing/ambiguous observations leave
gaps, without recruiting replacements. This is not a re-identification model.
"""
from __future__ import annotations
import math


class SelectionError(ValueError):
    """Safe failure: selected crew cannot be associated unambiguously."""


def validate_selection(value):
    """Return an independent canonical copy; coordinates are fractions [0, 1]."""
    if not isinstance(value, dict):
        raise SelectionError('invalid_selection')
    expected = {'version', 'roi', 'seeds', 'confirmed_same_boat'}
    if value.get('version') == 2:
        expected.add('reference_seconds')
    if set(value) != expected:
        raise SelectionError('invalid_selection')
    if type(value['version']) is not int or value['version'] not in (1, 2) or value['confirmed_same_boat'] is not True:
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
    result = {'version': value['version'], 'roi': roi, 'seeds': seeds, 'confirmed_same_boat': True}
    if value['version'] == 2:
        ref = value['reference_seconds']
        if type(ref) not in (int, float) or not math.isfinite(ref) or not 0 <= ref <= 600:
            raise SelectionError('invalid_reference_time')
        result['reference_seconds'] = float(ref)
    return result


def _forward_tracks(dets, meta, selection):
    """Keep eight selected identities, with gaps for uncertain/missing observations.

    The ROI constrains initialization only. Constant-velocity prediction follows
    the crew outside it; mutual-unique gates reject competing associations. A
    short absence (at most 0.75 seconds) can be reacquired. Longer losses retire
    that slot for this run: geometry alone cannot establish a returning identity.
    Predictions are NEVER inserted into the measured keypoint history.
    """
    import numpy as np
    selected = validate_selection(selection)
    scale = np.array([meta['width'], meta['height']], float)
    fps = float(meta.get('fps', 15.0))
    if (not np.isfinite(scale).all() or (scale <= 0).any() or not len(dets)
            or not math.isfinite(fps) or fps <= 0):
        raise SelectionError('selection_unavailable')
    roi = np.array(selected['roi']) * np.tile(scale, 2)
    seeds = np.array(selected['seeds']) * scale
    history = {i: {'frames': [], 'boxes': [], 'kpts': []} for i in range(8)}
    previous = None
    velocity = np.zeros((8, 2))
    seen_at = np.zeros(8, dtype=int)
    max_gap = max(1, int(fps * .75))
    for fi, (boxes, kpts) in enumerate(dets):
        boxes, kpts = np.asarray(boxes, float), np.asarray(kpts, float)
        if boxes.ndim != 2 or boxes.shape[1:] != (4,) or kpts.shape != (len(boxes), 17, 3):
            raise SelectionError('selection_unavailable')
        centres = (boxes[:, :2] + boxes[:, 2:]) / 2
        valid = (np.isfinite(boxes).all(axis=1)
                 & np.isfinite(kpts).all(axis=(1, 2))
                 & (boxes[:, 2:] > boxes[:, :2]).all(axis=1)
                 & (kpts[:, 5:13, 2].mean(axis=1) >= .25))
        if fi == 0:
            valid &= ((centres >= roi[:2]) & (centres <= roi[2:])).all(axis=1)
        boxes, kpts, centres = boxes[valid], kpts[valid], centres[valid]
        if previous is None:
            matches = (((seeds[:, None, :] >= boxes[None, :, :2])
                        & (seeds[:, None, :] <= boxes[None, :, 2:])).all(axis=2))
            if len(boxes) < 8 or not (matches.sum(axis=1) == 1).all():
                raise SelectionError('selected_crew_lost_or_ambiguous')
            indices = matches.argmax(axis=1)
            if len(set(indices)) != 8:
                raise SelectionError('selected_crew_lost_or_ambiguous')
            previous = boxes[indices].copy()
            accepted = list(enumerate(indices))
        else:
            gap = fi - seen_at
            old_centres = (previous[:, :2] + previous[:, 2:]) / 2
            prediction = old_centres + velocity * gap[:, None]
            sizes = previous[:, 2:] - previous[:, :2]
            # Never grow uncertainty indefinitely or jump a full seat pitch.
            gates = np.maximum(sizes * .60, 2.0)
            separation = np.linalg.norm(prediction[:, None] - prediction[None], axis=2)
            np.fill_diagonal(separation, np.inf)
            radius = np.maximum(2.0, separation.min(axis=1) * .45)
            gates[:, 0] = np.minimum(gates[:, 0], radius)
            delta = centres[None] - prediction[:, None]
            ratios = (boxes[:, 2:] - boxes[:, :2])[None] / sizes[:, None]
            matches = ((np.abs(delta) <= gates[:, None]).all(axis=2)
                       & ((ratios >= .45) & (ratios <= 2.2)).all(axis=2)
                       & (gap[:, None] <= max_gap))
            accepted = []
            # A detection must belong to only one live slot, and that slot must
            # have only one eligible detection. No greedy fallback on ambiguity.
            for i in np.flatnonzero(matches.sum(axis=1) == 1):
                j = int(np.flatnonzero(matches[i])[0])
                if matches[:, j].sum() == 1:
                    accepted.append((int(i), j))
            if accepted:
                steps = np.array([(centres[j] - old_centres[i]) / gap[i]
                                  for i, j in accepted])
                common = np.median(steps, axis=0)
                # Reject individual leaps relative to the crew rather than
                # failing seven otherwise usable rowers.
                accepted = [(i, j) for (i, j), step in zip(accepted, steps)
                            if len(steps) < 3 or (np.abs(step - common) <= gates[i]).all()]
                for i, j in accepted:
                    step = (centres[j] - old_centres[i]) / gap[i]
                    velocity[i] = .5 * velocity[i] + .5 * step
                    previous[i] = boxes[j]
                    seen_at[i] = fi
        for i, j in accepted:
            history[i]['frames'].append(fi)
            history[i]['boxes'].append(boxes[j].copy())
            history[i]['kpts'].append(kpts[j].copy())
    return {i: {'frames': np.asarray(t['frames'], dtype=int),
                'boxes': np.asarray(t['boxes'], dtype=float).reshape(-1, 4),
                'kpts': np.asarray(t['kpts'], dtype=float).reshape(-1, 17, 3)}
            for i, t in history.items()}


def locked_tracks(dets, meta, selection):
    """Track both directions from a confirmed reference; never invent observations."""
    import numpy as np
    selected = validate_selection(selection)
    if selected['version'] == 1:
        return _forward_tracks(dets, meta, selected)
    anchor = int(round(selected['reference_seconds'] * float(meta['fps'])))
    if not 0 <= anchor < len(dets):
        raise SelectionError('reference_outside_video')
    legacy = {k: v for k, v in selected.items() if k != 'reference_seconds'}
    legacy['version'] = 1
    forward = _forward_tracks(dets[anchor:], meta, legacy)
    backward = _forward_tracks([dets[anchor]] + list(reversed(dets[:anchor])), meta, legacy)
    result = {}
    for tid in forward:
        f, b = forward[tid], backward[tid]
        keep = b['frames'] > 0
        frames = np.r_[anchor - b['frames'][keep], anchor + f['frames']]
        order = np.argsort(frames)
        result[tid] = {
            'frames': frames[order],
            'boxes': np.concatenate([b['boxes'][keep], f['boxes']])[order],
            'kpts': np.concatenate([b['kpts'][keep], f['kpts']])[order],
        }
    return result
