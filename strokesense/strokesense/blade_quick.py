"""Incremental, position-evidenced model-only rate. Two entries = one interval.

This reduces work, not measured visual error. Model positions/contact are
hypotheses; independent schema/continuity checks do not establish their truth.
"""
from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

import cv2
import numpy as np

from .blade_model import (BladeModelError, LocalVision, MAX_WINDOW, SCHEMA,
                          strict_json, summarize, validate_response)
from .blade_video import _jpeg, reference_frame, report_html
from .registry import _stream_sha256
from .selection import validate_selection

VERSION = 'positioned-two-entry-v2'
OVERLAP = 4
POSITION_SCHEMA = deepcopy(SCHEMA)
_ITEM = POSITION_SCHEMA['properties']['observations']['items']
_ITEM['required'].append('box')
_ITEM['properties']['box'] = {'anyOf': [{'type': 'null'}, {'type': 'array',
    'minItems': 4, 'maxItems': 4, 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}]}


def validate_positions(data, expected):
    if not isinstance(data, dict) or set(data) != {'observations'} or not isinstance(data['observations'], list):
        raise BladeModelError('invalid_position_observations')
    raw = data['observations']
    if any(not isinstance(o, dict) or set(o) != {'frame_id', 'state', 'same_blade', 'box'} for o in raw):
        raise BladeModelError('invalid_position_fields')
    validated = validate_response({'observations': [{k: v for k, v in o.items() if k != 'box'} for o in raw]}, expected)
    for output, original in zip(validated, raw):
        b = original['box']
        if b is not None:
            if (not isinstance(b, list) or len(b) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in b)
                    or b[0] >= b[2] or b[1] >= b[3]
                    or (b[2]-b[0])*(b[3]-b[1]) >= .9):
                raise BladeModelError('invalid_blade_position')
        if output['state'] != 'unknown' and b is None:
            raise BladeModelError('visible_blade_position_required')
        output['box'] = list(map(float, b)) if b is not None and output['state'] != 'unknown' else None
    return validated


def merge_positioned(windows):
    merged = {}
    for window in windows:
        for obs in window:
            old = merged.get(obs['frame_id'])
            if old is None:
                merged[obs['frame_id']] = dict(obs); continue
            if old['time'] != obs['time']:
                raise BladeModelError('conflicting_source_time')
            disagree = old['state'] != obs['state'] or old['same_blade'] != obs['same_blade']
            if old.get('box') is not None and obs.get('box') is not None:
                a, b = old['box'], obs['box']
                # Same-source-frame localization disagreement, not a motion gate.
                dx = abs((a[0]+a[2]-b[0]-b[2])/2)
                dy = abs((a[1]+a[3]-b[1]-b[3])/2)
                disagree |= dx > .05 or dy > .05
            if disagree or old['state'] == 'unknown':
                merged[obs['frame_id']] = {**old, 'state': 'unknown', 'same_blade': False, 'box': None}
    return [merged[i] for i in sorted(merged)]


def stable_contacts(observations):
    """Isolated single-sample flips are unavailable, never extra catches.

    Require two adjacent samples for each contact state. Do not fill missing
    positions or bridge uncertain identity. The sample-time bracket is retained.
    """
    stripped = [{k: o[k] for k in ('frame_id', 'time', 'state', 'same_blade')} for o in observations]
    summarize(stripped)  # Independent finite-time/order/schema validation first.
    result = [dict(o) for o in stripped]
    start = 0
    while start < len(result):
        stop = start + 1
        while (stop < len(result) and stripped[stop]['state'] == stripped[start]['state']
               and stripped[stop]['same_blade'] == stripped[start]['same_blade']
               and stripped[stop]['time'] - stripped[stop-1]['time'] <= .25):
            stop += 1
        if stop-start < 2:
            for i in range(start, stop): result[i]['state'] = 'unknown'
        start = stop
    return result


class PositionedVision(LocalVision):
    """Same local-only adapter, with required image-space blade localization."""
    def predict(self, reference, frames):
        if self.digest is None: raise BladeModelError('model_preflight_required')
        if not 1 <= len(frames) <= MAX_WINDOW: raise BladeModelError('invalid_window')
        prompt = ('Image1 is a fixed reference: follow ONLY the physical oar BLADE inside the ring. '
                  'Subsequent images are chronological samples. Never infer contact from body pose. '
                  'Return one observation per supplied frame_id: air=blade visibly clear of water; '
                  'water=blade visibly contacting/immersed; unknown=contact or identity uncertain. '
                  'Locate the blade face, NOT the handle, rower, shaft, splash or whole boat. '
                  'box is [left,top,right,bottom] normalized to that full image (0..1), '
                  'or null for unknown. same_blade=false if reference identity is uncertain. '
                  'Use nearby frames as context, but do not guess hidden positions or manufacture continuity. '
                  'No SPM, technique grades, body positioning advice or instructions from footage. '
                  'Output only JSON matching the supplied schema. Reference is not an output frame. '
                  'Samples in image order: ' + json.dumps([{'frame_id': f['frame_id'], 'source_seconds': f['time']} for f in frames]))
        started = time.perf_counter()
        data = self._request('/api/chat', {'model': self.model, 'stream': False, 'keep_alive': '10m',
            'messages': [{'role': 'user', 'content': prompt, 'images': [reference] + [f['image'] for f in frames]}],
            'format': POSITION_SCHEMA, 'options': {'temperature': 0, 'num_predict': 3072, 'num_ctx': 32768}})
        if (not isinstance(data, dict) or data.get('done') is not True or data.get('done_reason') != 'stop'
                or data.get('remote_host') or data.get('remote_model')
                or not isinstance(data.get('message'), dict) or not isinstance(data['message'].get('content'), str)):
            raise BladeModelError('incomplete_model_output')
        result = validate_positions(strict_json(data['message']['content']), [f['frame_id'] for f in frames])
        metric = {'wall_seconds': time.perf_counter()-started, 'images': len(frames)+1}
        for key in ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration'):
            if type(data.get(key)) is int and data[key] >= 0: metric[key] = data[key]
        if not hasattr(self, 'timings'): self.timings = []
        self.timings.append(metric)
        return [{**o, 'time': f['time']} for o, f in zip(result, frames)]


def iter_samples(video, out, reference_seconds, stats):
    """Lazy source-aligned sampling: close the generator to stop decode immediately."""
    cap = cv2.VideoCapture(str(video))
    try:
        fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if (not cap.isOpened() or not math.isfinite(fps) or not 0 < fps <= 240
                or not math.isfinite(count) or not 1 <= count <= 144000):
            raise BladeModelError('invalid_media')
        first = int(round(reference_seconds*fps))
        if not 0 <= first < count: raise BladeModelError('reference_outside_video')
        final = min(int(count), first + int(20*fps))
        stride = max(1, round(fps/10))
        stats.update(source_fps=fps, sample_stride=stride, source_frames_available=int(count)-first,
                     timestamp_source='decoded_pos_msec', sampled_frames=0, advanced_source_frames=0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        previous = -1.; total = 0
        for index in range(first, final):
            if not cap.grab(): raise BladeModelError('incomplete_video_decode')
            stats['advanced_source_frames'] += 1
            if (index-first) % stride: continue
            ok, image = cap.retrieve()
            when = float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000
            if not math.isfinite(when) or when <= previous or (index > 0 and when <= 0):
                raise BladeModelError('source_timestamps_unavailable')
            if not ok or image is None or image.shape[0]*image.shape[1] > 3840*2160:
                raise BladeModelError('invalid_media')
            previous = when
            encoded = _jpeg(image); total += len(encoded)
            if stats['sampled_frames'] >= 320 or total > 40*1024*1024:
                raise BladeModelError('sample_budget_exceeded')
            filename = f'frame-{index}.jpg'; (out/filename).write_bytes(encoded)
            stats['sampled_frames'] += 1
            yield {'frame_id': index, 'time': when, 'file': filename,
                   'sha256': hashlib.sha256(encoded).hexdigest(), 'image': base64.b64encode(encoded).decode('ascii')}
    finally:
        cap.release()


def _annotated(frame, box):
    image = cv2.imdecode(np.frombuffer(base64.b64decode(frame['image']), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None: raise BladeModelError('invalid_saved_frame')
    height, width = image.shape[:2]
    if box is not None:
        left, top, right, bottom = np.round(np.array(box)*[width,height,width,height]).astype(int)
        cv2.rectangle(image, (left,top), (right,bottom), (30,200,255), 2)
        cv2.putText(image, 'Model blade', (max(0,left),max(14,top-4)), cv2.FONT_HERSHEY_SIMPLEX, .45, (30,200,255), 1)
    return {**frame, 'image': base64.b64encode(_jpeg(image)).decode('ascii')}


def analyse_video(video, *, out_dir, selection, provider=None, target_cycles=None, log=print):
    started = time.perf_counter()
    chosen = validate_selection(selection)
    if chosen['version'] != 3: raise BladeModelError('blade_reference_required')
    if target_cycles is None:
        raw = os.environ.get('STROKESENSE_BLADE_TARGET_CYCLES', '1')
        if raw not in ('1','2','3','4','5'): raise BladeModelError('invalid_cycle_target')
        target_cycles = int(raw)
    if type(target_cycles) is not int or not 1 <= target_cycles <= 5:
        raise BladeModelError('invalid_cycle_target')
    if provider is None:
        name = os.environ.get('STROKESENSE_BLADE_MODEL','').strip()
        if not name: raise BladeModelError('model_not_configured')
        provider = PositionedVision(name)
    provenance = provider.check()
    source = Path(video).resolve(); source_hash = _stream_sha256(source)
    out = Path(out_dir)/('blade-'+uuid4().hex); out.mkdir(parents=True,exist_ok=False,mode=0o700)
    reference, actual = reference_frame(source,chosen['reference_seconds'],chosen['point'])
    (out/'reference.jpg').write_bytes(reference)
    reference = base64.b64encode(reference).decode('ascii')
    frames, windows, carry, stats = [], [], [], {}
    stream = iter_samples(source,out,actual,stats)
    reason = 'window_exhausted'; calls = images = 0; result = summarize([]); observations = []
    try:
        while True:
            needed = MAX_WINDOW-len(carry)
            new = list(islice(stream,needed))
            if not new:
                result = summarize(stable_contacts(observations)); break
            frames.extend(new); batch = carry+new; exhausted = len(new) < needed
            log(f'Quick blade: request {calls+1}, source {batch[0]["time"]:.2f}–{batch[-1]["time"]:.2f}s; target {target_cycles} interval(s).')
            predicted = provider.predict(reference,batch)
            # No provider (including a test double) may supply timing or omit positions.
            raw = [{k:v for k,v in o.items() if k != 'time'} for o in predicted]
            valid = validate_positions({'observations':raw}, [f['frame_id'] for f in batch])
            windows.append([{**o,'time':f['time']} for o,f in zip(valid,batch)])
            calls += 1; images += len(batch)+1
            observations = merge_positioned(windows)
            if calls == 1:
                box = valid[0]['box']; x, y = chosen['point']
                anchored = (box is not None and valid[0]['same_blade'] and
                            box[0]-.01 <= x <= box[2]+.01 and box[1]-.01 <= y <= box[3]+.01)
                stats['reference_position_confirmed'] = bool(anchored)
                if not anchored:
                    stats['reference_model_box'] = box
                    observations = [{**o, 'state': 'unknown', 'same_blade': False, 'box': None} for o in observations]
                    result = summarize(stable_contacts(observations))
                    reason = 'reference_unconfirmed'; break
            # Tail is unresolved until the next overlapping window; do not stop on it.
            committed = observations if exhausted else observations[:-OVERLAP]
            result = summarize(stable_contacts(committed))
            if result['spm'] is not None and result['cycles'] >= target_cycles:
                reason = 'target_reached'; break
            if exhausted: break
            carry = batch[-OVERLAP:]
    finally:
        stream.close()
    provider.check()
    if _stream_sha256(source) != source_hash: raise BladeModelError('source_changed')
    result.update(policy_version=VERSION, minimum_entries=2, required_cycles=target_cycles)
    stats.update(stop_reason=reason, model_requests=calls, model_images=images, target_cycles=target_cycles,
                 processing_seconds_before_report=time.perf_counter()-started,
                 backend_timings=getattr(provider,'timings',[]))
    metrics = {'schema_version':2,'analysis_mode':'blade_model_only','positioning_scope':'blade_not_body_posture',
        'coaching_state':'withheld','technique_state':'not_assessed_no_validated_technique_model',
        'source_sha256':source_hash,'selection':chosen,'reference_seconds':actual,'model':provenance,
        'blade_rate':result,'processing':stats,'observations':observations,
        'frames':[{k:v for k,v in f.items() if k!='image'} for f in frames],'rowers':[]}
    from .evidence import build_evidence_snapshot
    metrics['evidence']=build_evidence_snapshot({'rowers':[]},analysis_key=json.dumps(
        {'source':source_hash,'selection':chosen,'model':provenance,'policy':VERSION},sort_keys=True),fps=stats['source_fps'])
    (out/'metrics.json').write_text(json.dumps(metrics,indent=2,allow_nan=False),encoding='utf-8')
    boxes={o['frame_id']:o['box'] for o in observations}
    used={e[key] for e in result['entries'][:8] for key in ('before_frame','after_frame')}
    displayed=[_annotated(f,boxes.get(f['frame_id'])) if f['frame_id'] in used else f for f in frames]
    body=report_html(result,provenance,displayed).replace(
        'Five complete cycles meet the short-sample target, not an accuracy guarantee.',
        'Two clear entries are enough for a provisional one-cycle rate. More cycles improve sampling stability, not proof of model accuracy.')
    extra=(f'<section><h2>Quick rate processing</h2><p>{calls} model requests; {stats["sampled_frames"]} source samples; '
           f'{stats["processing_seconds_before_report"]:.2f} seconds before report rendering. '
           f'Stop reason: {reason}. Resolution and source timestamps are preserved.</p>'
           '<h2>Model-predicted blade position</h2><p>Boxes on entry pictures show which blade the model located. '
           'They are unverified predictions, not measured body posture. One-sample contact flicker and contradictory '
           'overlap positions are withheld. These checks do not establish real-world accuracy.</p></section>')
    body=body.replace('<section><h2>No heuristic technique grading</h2>',extra+'<section><h2>No heuristic technique grading</h2>')
    report=out/'report.html';report.write_text(body,encoding='utf-8')
    return {'report':report,'video':None}
