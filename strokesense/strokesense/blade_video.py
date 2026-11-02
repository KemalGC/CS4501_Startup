"""Bounded local model-only blade-rate job, with privately saved frame evidence."""
from __future__ import annotations
import base64
import hashlib
import html
import json
import math
import os
from pathlib import Path
from uuid import uuid4

import cv2

from .blade_model import BladeModelError, LocalVision, MAX_WINDOW, merge_observations, summarize
from .selection import validate_selection


def _jpeg(image):
    height, width = image.shape[:2]
    if width > 1280:
        image = cv2.resize(image, (1280, round(height * 1280 / width)))
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 72])
    if not ok or len(encoded) > 500000: raise BladeModelError('preview_too_large')
    return encoded.tobytes()


def reference_frame(video, seconds, point=None):
    cap = cv2.VideoCapture(str(video))
    try:
        fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(fps) or not 0 < fps <= 240 or count < 1:
            raise BladeModelError('invalid_media')
        index = int(round(seconds * fps))
        if not 0 <= index < count: raise BladeModelError('reference_outside_video')
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, image = cap.read()
        if not ok or image is None or image.shape[0] * image.shape[1] > 3840 * 2160:
            raise BladeModelError('invalid_media')
        actual = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000
        if not math.isfinite(actual) or (index > 0 and actual <= 0):
            raise BladeModelError('source_timestamps_unavailable')
        if point is not None:
            x, y = (round(point[0] * image.shape[1]), round(point[1] * image.shape[0]))
            cv2.circle(image, (x, y), max(12, image.shape[1] // 50), (0, 0, 255), 3)
        return _jpeg(image), actual
    finally:
        cap.release()


def sample_video(video, out, reference_seconds):
    """At most 20 seconds/10 fps. Decode source timestamps, not invented times."""
    cap = cv2.VideoCapture(str(video))
    records = []
    total = 0
    try:
        fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(fps) or not 0 < fps <= 240 or not 1 <= count <= 144000:
            raise BladeModelError('invalid_media')
        start = max(0., reference_seconds - 5.)
        first, final = int(start * fps), min(int(count), int((start + 20.) * fps))
        stride = max(1, int(round(fps / 10)))
        if final <= first: raise BladeModelError('invalid_sampling_window')
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        previous = -1.
        for frame_id in range(first, final):
            ok, image = cap.read()
            if not ok: raise BladeModelError('incomplete_video_decode')
            if (frame_id - first) % stride: continue
            when = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000
            if not math.isfinite(when) or when <= previous or (frame_id > 0 and when <= 0):
                raise BladeModelError('source_timestamps_unavailable')
            previous = when
            if image is None or image.shape[0] * image.shape[1] > 3840 * 2160:
                raise BladeModelError('invalid_media')
            encoded = _jpeg(image)
            total += len(encoded)
            if len(records) >= 320 or total > 40 * 1024 * 1024:
                raise BladeModelError('sample_budget_exceeded')
            filename = f'frame-{frame_id}.jpg'
            (out / filename).write_bytes(encoded)
            records.append({'frame_id': frame_id, 'time': when, 'file': filename,
                            'sha256': hashlib.sha256(encoded).hexdigest(),
                            'image': base64.b64encode(encoded).decode('ascii')})
        if not records: raise BladeModelError('no_sampled_frames')
        return records, {'source_fps': fps, 'timestamp_source': 'decoded_pos_msec',
                         'sample_stride': stride, 'start_seconds': records[0]['time'],
                         'end_seconds': records[-1]['time']}
    finally:
        cap.release()


def analyse_video(video, *, out_dir, selection, provider=None, log=print):
    """Standalone model path. Does not import/run the pose stroke/fault analyzer."""
    selected = validate_selection(selection)
    if selected['version'] != 3: raise BladeModelError('blade_reference_required')
    model = os.environ.get('STROKESENSE_BLADE_MODEL', '').strip()
    if provider is None:
        if not model: raise BladeModelError('model_not_configured')
        provider = LocalVision(model)
    provenance = provider.check()  # Before decoding/private image transmission.
    # Preserve prior runs, including repeated direct calls for the same video.
    out = Path(out_dir) / ('blade-' + uuid4().hex)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = Path(video).resolve()
    from .registry import _stream_sha256
    source_hash = _stream_sha256(source)
    reference, actual_reference = reference_frame(source, selected['reference_seconds'], selected['point'])
    (out / 'reference.jpg').write_bytes(reference)
    encoded_ref = base64.b64encode(reference).decode('ascii')
    frames, media = sample_video(source, out, actual_reference)
    windows = []
    # Four shared frames establish agreement; discrepancies become unknown.
    for offset in range(0, len(frames), MAX_WINDOW - 4):
        batch = frames[offset:offset + MAX_WINDOW]
        if offset and len(batch) <= 4: break
        log(f'Blade model: sampled frames {offset + 1}-{offset + len(batch)} / {len(frames)}')
        windows.append(provider.predict(encoded_ref, batch))
    provider.check()  # Same installed weights throughout this run.
    if source_hash != _stream_sha256(source): raise BladeModelError('source_changed')
    observations = merge_observations(windows)
    result = summarize(observations)
    metrics = {'schema_version': 1, 'analysis_mode': 'blade_model_only',
        'coaching_state': 'withheld', 'source_sha256': source_hash,
        'selection': selected, 'reference_seconds': actual_reference,
        'model': provenance, 'sampling': media, 'blade_rate': result,
        'observations': observations,
        'frames': [{k: v for k, v in f.items() if k != 'image'} for f in frames],
        'rowers': [], 'technique_state': 'not_assessed_no_validated_technique_model'}
    # Empty legacy evidence keeps the existing navigation integrity checks honest:
    # blade events are saved above, not mislabeled as pose/fault observations.
    from .evidence import build_evidence_snapshot
    metrics['evidence'] = build_evidence_snapshot({'rowers': []},
        analysis_key=json.dumps({'source': source_hash, 'model': provenance, 'selection': selected}, sort_keys=True),
        fps=media['source_fps'])
    (out / 'metrics.json').write_text(json.dumps(metrics, indent=2, allow_nan=False), encoding='utf-8')
    report = out / 'report.html'
    report.write_text(report_html(result, provenance, frames), encoding='utf-8')
    return {'report': report, 'video': None}


def report_html(result, model, frames):
    rate = 'Unavailable' if result['spm'] is None else f"{result['spm']:.1f} SPM"
    rows = ''.join(f'<tr><td>{e["id"]}</td><td>{e["lower_seconds"]:.3f}–{e["upper_seconds"]:.3f} s</td>'
                   f'<td>{e["before_frame"]} → {e["after_frame"]}</td></tr>' for e in result['entries'])
    images = {f['frame_id']: f['image'] for f in frames}
    pictures = ''
    for entry in result['entries'][:8]:
        pair = ''.join(f'<figure><img alt="Source frame {entry[key]}" src="data:image/jpeg;base64,{images[entry[key]]}">'
                       f'<figcaption>{label}: frame {entry[key]}</figcaption></figure>'
                       for key, label in [('before_frame', 'Model: air'), ('after_frame', 'Model: water')])
        pictures += f'<section><h3>Entry {entry["id"]} — inspect both frames</h3><div class="pair">{pair}</div></section>'
    bounds = '' if result['spm_bounds'] is None else (f'<p>Sampling-only bounds: '
             f'{result["spm_bounds"][0]:.1f}–{result["spm_bounds"][1]:.1f} SPM. '
             'These do not include model or identity errors.</p>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>StrokeSense experimental blade-rate report</title><style>'
        'body{font:17px/1.6 system-ui,sans-serif;margin:0;background:#f3f6f7;color:#162031}'
        'main{max-width:1100px;margin:auto;padding:32px}section{background:white;padding:24px;margin:20px 0;border-radius:12px}'
        '.notice{border-left:5px solid #b15b11;padding:16px;background:#fff4e4}.rate{font-size:2.4em;font-weight:700}'
        'table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}'
        '.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}figure{margin:0}img{width:100%;height:auto}'
        'code{overflow-wrap:anywhere}@media(max-width:650px){main{padding:16px}.pair{grid-template-columns:1fr}}'
        '</style><main><h1>Blade-entry stroke rate</h1>'
        '<p class="notice"><strong>Experimental model estimate — not accuracy-validated.</strong> '
        'A local vision model classified one selected blade as air, water or unknown. '
        'Schema checks cannot prove correct contact or identity. Check the entry pictures before using the rate.</p>'
        f'<section><div class="rate">{rate}</div><p>{result["cycles"]} consecutive supported cycles in the longest visible run; '
        f'{len(result["entries"])} inferred entries overall. '
        f'{result["unknown_frames"]}/{result["sampled_frames"]} samples unknown.</p>{bounds}'
        '<p>Five complete cycles meet the short-sample target, not an accuracy guarantee. '
        'Entries of other oars are not added. Unknown observations break continuity.</p></section>'
        '<section><h2>No heuristic technique grading</h2><p>This mode does not run body-angle peak detection, '
        'technique fault rules, synthetic grades or posture curves. Technique coaching is withheld '
        'until a separately validated model is available.</p></section>'
        '<section><h2>Model-predicted entry brackets</h2><table><thead><tr><th>Entry</th><th>Source time</th>'
        f'<th>Source frames</th></tr></thead><tbody>{rows}</tbody></table></section>{pictures}'
        '<section><h2>Reproducibility</h2><p>Model: <code>' + html.escape(model['name']) + '</code><br>'
        'Digest: <code>' + html.escape(model['digest']) + '</code></p>'
        '<p>Frame hashes, classifications, timestamps and configuration are saved in the private metrics.json. '
        'At most eight entry image pairs are shown here. No live provider or coach approval is implied.</p></section></main></html>')
