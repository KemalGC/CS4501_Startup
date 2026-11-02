"""Selected-crew extraction and gap-aware analysis; no fabricated observations."""
from __future__ import annotations

import html
import numpy as np

from . import kinematics, strokes
from .selection import validate_selection

EXTRACTION_VERSION = 'dynamic-refined-full-frame-v3'
TRACKING_VERSION = 'selected-motion-gaps-v2'
STROKE_POLICY_VERSION = 'short-internal-gaps-v1'


def run_selected_video(video, detector, selection, *, tiles='auto', **kwargs):
    """Match the selection preview first, then search the entire moving scene.

    Full-frame tiling avoids freezing a horizontal band or ROI around the boat's
    initial location. Existing resize, sampling, metadata and CLI are reused.
    """
    from .pose import run_video, PoseDetector
    selected = validate_selection(selection)
    first = True

    def detect(image, tiles=None):
        nonlocal first
        height, width = image.shape[:2]
        x0 = y0 = 0
        if first and selected['version'] == 1:
            left, top, right, bottom = selected['roi']
            x0, y0 = int(left * width), int(top * height)
            image = image[y0:int(bottom * height), x0:int(right * width)]
            first = False
        if image.size == 0:
            raise ValueError('empty_selection_region')
        use_tiles = (PoseDetector.tile_grid(image.shape[1], image.shape[0])
                     if tile_mode == 'auto' else tile_mode)
        if selected['version'] == 2:
            from .multiframe import refined_detections
            boxes, scores, points = refined_detections(image, detector)
        else:
            boxes, scores, points = detector(image, tiles=use_tiles)
        boxes, points = boxes.copy(), points.copy()
        boxes[:, [0, 2]] += x0
        boxes[:, [1, 3]] += y0
        points[..., 0] += x0
        points[..., 1] += y0
        return boxes, scores, points

    tile_mode = tiles
    return run_video(video, detect, tiles=None, **kwargs)


def _runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))


def _analysis_blocks(visible, max_gap):
    """Join only bounded internal holes; never extrapolate a leading/trailing gap."""
    usable = visible.copy()
    for start, end in _runs(~visible):
        if start > 0 and end < len(visible) and end - start <= max_gap:
            usable[start:end] = True
    return list(_runs(usable))


def rowers_from_selected(pose, *, workers=4):
    """Measure cycles with >=90% observations and only <=0.2s internal holes.

    Kinematic interpolation is used only as an explicitly qualified short-gap
    estimate. Never fill the pose history or render missing values as observed.
    Long absence splits the analysis. Critical phase points must be observed.
    """
    from .crew import Rower
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must be an integer from 1 to 4')
    rowers = []
    for tid in sorted(pose.tracks):
        raw = pose.dense(tid)
        k = kinematics.build(raw, pose.fps)
        rower = Rower(tid=tid, seat=f'Selected {tid + 1}', k=k)
        rower.handle = np.full(pose.n_frames, np.nan)
        max_gap = max(0, int(np.floor(pose.fps * .2)))
        for start, end in _analysis_blocks(k.visible, max_gap):
            # At least one whole cycle is required even at the maximum rate.
            if end - start < max(5, int(np.ceil(pose.fps * 60 / 50)) + 1):
                continue
            segment = kinematics.sliced(k, start, end)
            found, handle = strokes.analyse(segment, workers=workers, max_gap_frames=max_gap)
            rower.handle[start:end] = handle
            for stroke in found:
                stroke.idx = len(rower.strokes)
                for name in ('catch', 'finish', 'next_catch', 'catch_t', 'next_catch_t'):
                    setattr(stroke, name, getattr(stroke, name) + int(start))
                rower.strokes.append(stroke)
        # Display gaps too; interpolated positions are not observations.
        for values in (k.px,):
            for series in values.values():
                series[~k.visible] = np.nan
        rower.summary = strokes.summarise(rower.strokes)
        observed = len(pose.tracks[tid]['frames'])
        rower.summary['tracking'] = {
            'version': TRACKING_VERSION,
            'observed_frames': observed,
            'total_frames': pose.n_frames,
            'missing_frames': pose.n_frames - observed,
            'usable_frames': int(k.visible.sum()),
            'state': 'partial' if observed < pose.n_frames else 'observed',
            'stroke_policy': STROKE_POLICY_VERSION,
            'measurement_workers': workers,
            'max_internal_gap_seconds': .2,
            'minimum_cycle_observed_fraction': .9,
        }
        rowers.append(rower)
    return rowers


def coverage_html(rowers):
    """Report measured denominators, not detector confidence or accuracy."""
    rows = []
    for rower in rowers:
        coverage = rower.summary.get('tracking')
        if coverage is None:
            continue
        observed, total = coverage['observed_frames'], coverage['total_frames']
        state = ('Insufficient continuous evidence' if not rower.strokes else
                 'Partial tracking' if observed < total else 'Tracked')
        rows.append(f'<li><strong>{html.escape(rower.seat)}</strong>: '
                    f'{observed} / {total} sampled frames observed; '
                    f'{coverage["missing_frames"]} unavailable. {state}.</li>')
    if not rows:
        return ''
    return ('<section class="card wide" aria-label="Tracking coverage">'
            '<h2>Tracking coverage</h2><p>Selected identities are retained when '
            'rowers leave view. Missing or ambiguous frames are not measured; '
            'scored cycles require at least 90% observed frames and observed catch/finish points. '
            'Only internal gaps up to 0.2 seconds may be estimated and are counted per stroke. A long loss is '
            'not automatically reassigned to a new person.</p><ul>' + ''.join(rows)
            + '</ul><p>This is observation coverage, not tracking accuracy or '
            'coach-verified technique.</p></section>')
