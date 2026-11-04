"""Package 5–7 eight-person-crew clips and real saved analysis for review.

This copies local, precomputed artifacts. It never fabricates model results,
participant answers, or ground truth, and never uploads media to GitHub.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

from .feedback import load_catalog
from .feedback_prepare import summarize_metrics


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _copy(source, destination):
    source = Path(source)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('missing_nonempty_artifact')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return _sha(destination)


def build_eights_study(selection_path, runs_dir, output, *, model_info=None):
    """Build a fresh study from a private selection JSON and actual run records.

    Each selection needs id/title, rowers=8, source, start/end, duration,
    target, path (trimmed browser MP4), thumbnail. Completed runs additionally
    require selection inference_sha256 to match their existing, nonempty input.
    Run records are named <id>.json and contain state, result_dir on success,
    elapsed_seconds, input.
    Missing/failed output yields an explicit diagnostic, never sample metrics.
    Existing studies are not replaced; their participant database is preserved.
    """
    selection = json.loads(Path(selection_path).read_text('utf-8'))
    if not isinstance(selection, list) or not 5 <= len(selection) <= 7:
        raise ValueError('five_to_seven_clips_required')
    seen = set()
    for item in selection:
        cid = item['id']
        if not isinstance(cid, str) or not re.fullmatch(r'[a-z0-9-]{1,64}', cid) or cid in seen:
            raise ValueError('invalid_or_duplicate_clip_id')
        seen.add(cid)
        if item.get('rowers') != 8:
            raise ValueError('eights_only')
        start, end, duration = item['start'], item['end'], item['duration']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end, duration)):
            raise ValueError('invalid_window')
        if start < 0 or end <= start or duration <= 0 or abs(end-start-duration) > .15:
            raise ValueError('invalid_window')
        if not isinstance(item.get('target'), str) or not item['target'].strip():
            raise ValueError('target_boat_required')
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('study_already_exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    model = json.loads(Path(model_info).read_text('utf-8')) if model_info else None
    catalog = {'schema_version': 1, 'title': 'StrokeSense — eights evaluation',
               'study_version': 'eights-2026-11-04-v1', 'expected_clips': len(selection),
               'created_utc': datetime.now(timezone.utc).isoformat(),
               'cohort': 'Eight-person crews only; the coxswain is excluded.',
               'reference_status': 'Human technical review pending. No participant responses are included.',
               'clips': []}
    with tempfile.TemporaryDirectory(prefix='.eights-study-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'study'
        stage.mkdir()
        for item in selection:
            cid = item['id']
            run = json.loads((Path(runs_dir)/f'{cid}.json').read_text('utf-8'))
            if run.get('clip_id') != cid:
                raise ValueError('analysis_clip_mismatch')
            inference_hash = None
            input_name = run.get('input')
            if run.get('state') == 'completed':
                expected_hash = item.get('inference_sha256')
                if not isinstance(expected_hash, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected_hash):
                    raise ValueError('selection_inference_sha256_required')
                if not isinstance(input_name, str) or not input_name:
                    raise ValueError('completed_inference_input_required')
                input_path = Path(input_name)
                if not input_path.is_file() or input_path.stat().st_size == 0:
                    raise ValueError('completed_inference_input_required')
                inference_hash = _sha(input_path)
                if inference_hash != expected_hash.lower():
                    raise ValueError('selected_inference_input_changed')
            elif isinstance(input_name, str) and input_name and Path(input_name).is_file():
                inference_hash = _sha(input_name)
            video, poster = f'media/{cid}.mp4', f'media/{cid}.jpg'
            preview_hash = _copy(item['path'], stage/video)
            if item.get('sha256') and preview_hash != item['sha256']:
                raise ValueError('selected_preview_changed')
            _copy(item['thumbnail'], stage/poster)
            report = f'results/{cid}/report.html'
            metrics = None
            clip = {'id': cid, 'title': item['title'], 'group_id': str(item['source']).split('/')[0],
                    'duration': item['duration'], 'video': video, 'poster': poster,
                    'report': report, 'expected_rowers': 8, 'target_boat': item['target']}
            provenance = {'source_recording': item['source'],
                          'original_window_seconds': {'start': item['start'], 'end': item['end']},
                          'preview_sha256': preview_hash,
                          'timestamp_basis': 'Seconds from the beginning of this trimmed clip. Add original window start to recover recording time.',
                          'target_boat': item['target'], 'expected_rowers': 8,
                          'selection_method': 'Assistant visual review, not independent human labels',
                          'selection_rationale': item.get('selection_rationale'),
                          'cut_reason': item.get('cut_reason'),
                          'view_limitations': item.get('limitations'),
                          'inference_elapsed_seconds': run.get('elapsed_seconds'),
                          'model': model}
            if inference_hash is not None:
                provenance['inference_input_sha256'] = inference_hash
            if run.get('state') == 'completed':
                result_dir = Path(run['result_dir'])
                metrics = json.loads((result_dir/'metrics.json').read_text('utf-8'))
                _copy(result_dir/'report.html', stage/report)
                clip['metrics'] = f'results/{cid}/metrics.json'
                _copy(result_dir/'metrics.json', stage/clip['metrics'])
                overlay = run.get('annotated')
                if overlay:
                    clip['annotated'] = f'results/{cid}/annotated.mp4'
                    _copy(overlay, stage/clip['annotated'])
                for name in ('validation.json', 'dominant.json'):
                    if (result_dir/name).is_file():
                        _copy(result_dir/name, stage/f'results/{cid}/{name}')
            else:
                reason = 'No reliable model report was produced for this clip.'
                (stage/report).parent.mkdir(parents=True, exist_ok=True)
                (stage/report).write_text('<!doctype html><meta charset="utf-8"><title>Analysis unavailable</title>'
                    '<h1>'+html.escape(item['title'])+'</h1><p>'+reason+'</p>'
                    '<p>Review the original footage and mark missing outputs as not applicable. '
                    'No posture, cadence, or timing values have been invented.</p>', encoding='utf-8')
            note = (f"Eight-person crew; exclude the coxswain. {item['target']} "
                    f"Original recording window: {item['start']:g}–{item['end']:g} seconds. "
                    'Player and evidence timestamps start at zero for this trimmed clip. '
                    'All model outputs are provisional and need visual review.')
            clip['analysis'] = summarize_metrics(metrics, start=0., end=float(item['duration']), note=note)
            clip['provenance'] = provenance
            catalog['clips'].append(clip)
        (stage/'catalog.json').write_text(json.dumps(catalog, indent=2, allow_nan=False), encoding='utf-8')
        load_catalog(stage/'catalog.json')
        stage.rename(output)
    return catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--runs-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-info', type=Path)
    args = parser.parse_args(argv)
    result = build_eights_study(args.selection, args.runs_dir, args.output, model_info=args.model_info)
    print(json.dumps({'clip_count': len(result['clips']), 'study': str(args.output.resolve()),
                      'participant_feedback': 'not_collected', 'publicly_deployed': False}))


if __name__ == '__main__':
    main()
