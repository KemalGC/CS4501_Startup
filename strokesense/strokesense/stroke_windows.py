"""Versioned, source-timed stroke windows; no guessed missing observations."""
import math


def manifest(rowers, fps, start_seconds=0.0):
    if (not math.isfinite(float(fps)) or fps <= 0
            or not math.isfinite(float(start_seconds)) or start_seconds < 0):
        raise ValueError('invalid_stroke_timebase')
    result = {'version': 1, 'timebase': 'source_video_seconds',
              'minimum_usable_strokes': 5, 'rowers': []}
    for rower in rowers:
        windows = []
        for stroke in rower.strokes:
            s = stroke.to_dict()
            observed = s.get('observed_frames')
            missing = s.get('gap_frames')
            if not observed:
                observed = missing = None  # Legacy evidence has no quality counts.
            windows.append({
                'stroke': s['idx'] + 1,
                'source_start_seconds': start_seconds + s['catch'] / fps,
                'source_finish_seconds': start_seconds + s['finish'] / fps,
                'source_end_seconds': start_seconds + s['next_catch'] / fps,
                'observed_frames': observed,
                'missing_frames': missing,
                'total_frames': s['next_catch'] - s['catch'] + 1,
                'contains_estimated_gap': missing > 0 if missing is not None else None})
        result['rowers'].append({'seat': rower.seat, 'track': rower.tid, 'windows': windows})
    return result
