"""Selected-crew extraction and gap-aware analysis; no fabricated observations."""
from __future__ import annotations

import html
import numpy as np

from . import kinematics, strokes
from .selection import validate_selection

EXTRACTION_VERSION = 'dynamic-full-frame-v2'
TRACKING_VERSION = 'selected-motion-gaps-v2'


def run_selected_video(video, detector, selection, *, tiles='auto', **kwargs):
    """Match the selection preview first, then search the entire moving scene.

    Full-frame tiling avoids freezing a horizontal band or ROI around the boat's
    initial location. Existing resize, sampling, metadata and CLI are reused.
    """
    from .pose import run_video, PoseDetector
    selected = validate_selection(selection)
    first = True
    index = 0
    reference = None
    if selected['version'] == 2:
        from .pose import cv2
        cap = cv2.VideoCapture(str(video))
        try:
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            if not np.isfinite(source_fps) or source_fps <= 0:
                raise ValueError('invalid_video_fps')
            target = kwargs.get('target_fps', 15)
            stride = max(1, round(source_fps / target)) if target else 1
            reference = round(selected['reference_seconds'] * source_fps / stride)
        finally:
            cap.release()

    def detect(image, tiles=None):
        nonlocal first, index
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
        if index == reference:
            from .multiframe import refined_detections
            boxes, scores, points = refined_detections(image, detector)
        else:
            boxes, scores, points = detector(image, tiles=use_tiles)
        index += 1
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


def rowers_from_selected(pose):
    """Analyze uninterrupted observed intervals; preserve original timestamps.

    No interpolation across absence is used for stroke scoring. The full-length
    kinematics is for display only and is masked by observed visibility.
    """
    from .crew import Rower
    rowers = []
    for tid in sorted(pose.tracks):
        raw = pose.dense(tid)
        k = kinematics.build(raw, pose.fps)
        rower = Rower(tid=tid, seat=f'Selected {tid + 1}', k=k)
        rower.handle = np.full(pose.n_frames, np.nan)
        for start, end in _runs(k.visible):
            # At least one whole cycle is required even at the maximum rate.
            if end - start < max(5, int(np.ceil(pose.fps * 60 / 50)) + 1):
                continue
            segment = kinematics.build(raw[start:end], pose.fps)
            found, handle = strokes.analyse(segment)
            rower.handle[start:end] = handle
            for stroke in found:
                stroke.idx = len(rower.strokes)
                for name in ('catch', 'finish', 'next_catch', 'catch_t', 'next_catch_t'):
                    setattr(stroke, name, getattr(stroke, name) + int(start))
                rower.strokes.append(stroke)
        # Display gaps too; interpolated positions are not observations.
        for values in (k.px, k.uv, k.angles):
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
            'only continuous visible stroke cycles are scored. A long loss is '
            'not automatically reassigned to a new person.</p><ul>' + ''.join(rows)
            + '</ul><p>This is observation coverage, not tracking accuracy or '
            'coach-verified technique.</p></section>')
