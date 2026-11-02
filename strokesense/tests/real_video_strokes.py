"""Actual public-video predictions through strict and short-gap stroke measurement.

The source is development footage, not held-out ground truth. Reference seeds
come from assistant inspection, not human-reviewed identity annotations. Counts
and coverage must not be presented as accuracy or coaching validation.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.pose import PoseDetector, PoseResult
from strokesense.multiframe import refined_detections
from strokesense.selection import locked_tracks, SelectionError
from strokesense import dynamic_crew, report
from real_video_compare import EIGHT_SEEDS
from real_video_smoke import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.video.is_file() or not args.model.is_file():
        parser.error('explicit existing local assets required')
    args.out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not cap.isOpened() or not 0 < fps <= 240:
        raise ValueError('invalid_media')
    stride = max(1, round(fps / 15))
    first = int(fps)
    indices = range(first, min(total, int(13 * fps)), stride)
    detector = PoseDetector(args.model)
    detections = []
    began = time.monotonic()
    try:
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = cap.read()
            if not ok:
                raise ValueError('decode_failed')
            h, w = image.shape[:2]
            if w > 1280:
                image = cv2.resize(image, (1280, round(h * 1280 / w)))
            h, w = image.shape[:2]
            boxes, scores, points = refined_detections(image, detector)
            detections.append((boxes, points))
            if len(detections) % 20 == 0:
                print('Real video sampled frames:', len(detections), flush=True)
    finally:
        cap.release()
    result = {'real_model_inference': True, 'human_labels': False,
              'identity_accuracy': 'unmeasured', 'technique_accuracy': 'unmeasured',
              'private_user_video_used': False, 'development_video': True,
              'source_sha256': digest(args.video), 'model_sha256': digest(args.model),
              'sampled_frames': len(detections), 'source_window_seconds': [1, 13],
              'model_elapsed_seconds': time.monotonic() - began}
    try:
        selected = {'version': 2, 'reference_seconds': 3.96-first/fps,
                    'roi': [0,0,1,1], 'seeds': EIGHT_SEEDS, 'confirmed_same_boat': True}
        meta = {'width': w, 'height': h, 'fps': fps/stride}
        tracks = locked_tracks(detections, meta, selected)
        pose = PoseResult(fps/stride, len(detections), w, h, tracks,
                          start=first/fps, stride=stride)
        original_blocks = dynamic_crew._analysis_blocks
        with patch.object(dynamic_crew, '_analysis_blocks',
                          side_effect=lambda visible, bound: original_blocks(visible, 0)):
            strict = dynamic_crew.rowers_from_selected(pose, workers=1)
        start = time.monotonic()
        serial = dynamic_crew.rowers_from_selected(pose, workers=1)
        serial_seconds = time.monotonic()-start
        start = time.monotonic()
        parallel = dynamic_crew.rowers_from_selected(pose, workers=4)
        parallel_seconds = time.monotonic()-start
        same = [[s.to_dict() for s in r.strokes] for r in serial] == [[s.to_dict() for s in r.strokes] for r in parallel]
        if not same:
            raise AssertionError('serial_parallel_measurements_differ')
        result.update({'observed_by_slot': [len(tracks[i]['frames']) for i in range(8)],
                       'strict_gap_strokes': [len(r.strokes) for r in strict],
                       'short_gap_strokes': [len(r.strokes) for r in parallel],
                       'short_assessment_ready': [len(r.strokes)>=5 for r in parallel],
                       'serial_parallel_equal': same, 'serial_measurement_seconds': serial_seconds,
                       'parallel_measurement_seconds': parallel_seconds,
                       'gap_containing_cycles': [sum(s.gap_frames>0 for s in r.strokes) for r in parallel]})
        report.build_json(parallel, {}, args.out/'stroke_windows.json', fps=pose.fps, start_seconds=pose.start)
    except SelectionError as exc:
        result['tracking_error'] = str(exc)
    (args.out/'quality.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
