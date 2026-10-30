"""First-frame person proposals, not boat recognition or tracking approval.

Only an installed runtime and cached model are used. The private /select route
checks clip permission and content hash before and after calling this module.
"""
from __future__ import annotations
import html
import importlib.util
import json
import threading
import cv2
import numpy as np
from .pose import DEFAULT_MODEL, PoseDetector

DETECTION_LOCK = threading.Lock()
_session = None
_session_key = None
_MESSAGES = {
    'model_unavailable': 'Automatic detection needs the local pose model and ONNX Runtime. Manual selection is still available.',
    'busy': 'Another preview is being detected. Reload this page when it finishes, or use manual selection.',
    'failed': 'Automatic detection could not finish. Manual selection is still available; check the local model installation.',
    'no_detections': 'No usable people were detected in the first frame. Use a clearer clip or manual selection.',
    'too_many': 'Too many detections for a reliable preview. Use a closer clip or select a boat region manually.',
}


class Preview(str):
    def __new__(cls, image, proposals):
        instance = super().__new__(cls, image)
        instance.proposals = proposals
        return instance


def detect_candidates(frame, detector):
    """Same resize/tiles as selected full-frame run_video; never choose a crew."""
    if frame.ndim != 3 or min(frame.shape[:2]) < 64 or frame.shape[0] * frame.shape[1] > 3840 * 2160:
        raise ValueError('invalid_preview')
    if frame.shape[1] > 1920:
        scale = 1920 / frame.shape[1]
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    height, width = frame.shape[:2]
    boxes, _, kpts = detector(frame, tiles=PoseDetector.tile_grid(width, height))
    boxes, kpts = np.asarray(boxes, float), np.asarray(kpts, float)
    if boxes.ndim != 2 or boxes.shape[1:] != (4,) or kpts.shape != (len(boxes), 17, 3):
        raise ValueError('invalid_detections')
    centres = (boxes[:, :2] + boxes[:, 2:]) / 2
    valid = (np.isfinite(boxes).all(axis=1) & np.isfinite(kpts).all(axis=(1, 2))
             & (boxes[:, 2:] > boxes[:, :2]).all(axis=1)
             & (centres >= [0, 0]).all(axis=1) & (centres <= [width, height]).all(axis=1)
             & (kpts[:, 5:13, 2].mean(axis=1) >= .25))
    boxes = boxes[valid] / np.array([width, height, width, height])
    if not len(boxes):
        return {'state': 'no_detections', 'candidates': []}
    if len(boxes) > 64:
        return {'state': 'too_many', 'candidates': []}
    boxes = boxes[np.lexsort((boxes[:, 0], boxes[:, 1]))]
    candidates = []
    for box in boxes:
        visible = np.clip(box, .0001, .9999)
        seed = None
        # Try central points first. A point inside two boxes is never offered as
        # a confirmed initial target. Round exactly as the existing form does.
        positions = [(x, y) for x in np.linspace(.15, .85, 15) for y in np.linspace(.15, .85, 15)]
        positions.sort(key=lambda p: (p[0]-.5)**2 + (p[1]-.5)**2)
        for relative in positions:
            point = np.round(visible[:2] + np.array(relative)*(visible[2:]-visible[:2]), 5)
            contains = ((point >= boxes[:, :2]) & (point <= boxes[:, 2:])).all(axis=1)
            if contains.sum() == 1 and (point > box[:2]).all() and (point < box[2:]).all():
                if all(c['seed'] is None or np.linalg.norm(point-c['seed']) >= .002 for c in candidates):
                    seed = point.tolist()
                    break
        candidates.append({'id': len(candidates)+1, 'box': visible.tolist(), 'seed': seed})
    return {'state': 'ready', 'candidates': candidates}


def suggest(frame):
    """Serialize local preview inference; never download weights during a GET."""
    global _session, _session_key
    if not DETECTION_LOCK.acquire(blocking=False):
        return {'state': 'busy', 'candidates': []}
    try:
        if not DEFAULT_MODEL.is_file() or importlib.util.find_spec('onnxruntime') is None:
            return {'state': 'model_unavailable', 'candidates': []}
        stat = DEFAULT_MODEL.stat()
        key = (str(DEFAULT_MODEL.resolve()), stat.st_size, stat.st_mtime_ns)
        if _session is None or key != _session_key:
            _session = PoseDetector(DEFAULT_MODEL)
            _session_key = key
        return detect_candidates(frame, _session)
    except Exception:
        # No private paths, frame data, provider internals or raw error strings.
        return {'state': 'failed', 'candidates': []}
    finally:
        DETECTION_LOCK.release()


def controls(image):
    proposals = getattr(image, 'proposals', None)
    if not proposals:
        return ''
    candidates = proposals['candidates']
    if not candidates:
        return '<p role="status">' + _MESSAGES.get(proposals['state'], _MESSAGES['failed']) + '</p>'
    payload = html.escape(json.dumps(candidates, separators=(',', ':'), allow_nan=False), quote=True)
    labels = ''.join(
        '<label style="display:inline-flex;align-items:center;gap:.4rem;padding:.5rem">'
        f'<input type="checkbox" class="person-toggle" data-person="{i}"'
        + (' disabled' if c['seed'] is None else '')
        + f'>Person {c["id"]}' + (' (overlap; unavailable)' if c['seed'] is None else '') + '</label>'
        for i, c in enumerate(candidates))
    usable = sum(c['seed'] is not None for c in candidates)
    warning = (f'<p role="status">Only {usable} usable detections. Eight are required; use a clearer clip or manual selection.</p>' if usable < 8 else '')
    return (warning + f'<fieldset id="detected-people" data-candidates="{payload}">'
            '<legend>Detected people — confirm your crew</legend>'
            '<p><span id="candidate-count">0 of 8 selected.</span> Click numbered boxes or use these toggles. Choose only '
            'the eight rowers in your boat, not the coxswain or another crew. '
            'People detection does not identify boat membership.</p>'
            '<p>Automatic mode keeps the full frame for consistent detection; only the '
            'eight people you confirm enter the selected crew. Later tracking can still '
            'stop if people become hidden or ambiguous.</p>' + labels + '</fieldset>'
            '<p><button type="button" id="selection-manual">Use manual selection</button> '
            '<button type="button" id="selection-auto">Use detected people</button></p>')
