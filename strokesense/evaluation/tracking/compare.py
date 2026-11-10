"""Replay identical cached detections through frozen and current tracking models.

Run from strokesense: .venv/bin/python evaluation/tracking/compare.py
No video upload or detector download. Labels are an assistant-reviewed audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strokesense.pose import crew_tracks, load_detections
import baseline


def audit(tracks, detections, labels):
    correct = wrong = missing = detectable = 0
    for frame, seats in labels.items():
        fi = int(frame)
        for seat, indices in enumerate(seats):
            detectable += bool(indices)
            track = tracks.get(seat)
            found = np.flatnonzero(track['frames'] == fi) if track is not None else []
            if not len(found):
                missing += 1
                continue
            box = track['boxes'][found[0]]
            matches = [j for j, b in enumerate(detections[fi][0]) if np.array_equal(box, b)]
            if set(matches).intersection(indices):
                correct += 1
            else:
                wrong += 1
    return dict(correct=correct, wrong=wrong, missing=missing,
                detectable_seat_frames=detectable, total_seat_frames=8*len(labels))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caches', type=Path, default=Path('results/tracking-v2'))
    parser.add_argument('--out', type=Path, default=Path('results/model-tracking-evaluation'))
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    labels = json.loads(Path(__file__).with_name('labels.json').read_text())
    report = {'provenance': labels['provenance'], 'segments': {}}
    for segment, annotation in labels['segments'].items():
        paths = list((args.caches / segment).glob('*/detections.npz'))
        if len(paths) != 1: raise ValueError(f'Expected one detection cache for {segment}')
        path = paths[0]; detections, meta = load_detections(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != labels['cache_sha256'][segment]:
            raise ValueError(f'Labels do not apply to changed cache: {segment}')
        result = {'cache_sha256': digest,
                  'sampled_frames': len(detections), 'fps': meta['fps'], 'start': meta['start']}
        for name, fn in [('baseline', baseline.crew_tracks), ('candidate', crew_tracks)]:
            start = time.perf_counter()
            tracks, _, _ = fn(detections, meta['fps'], expected_seats=8)
            result[name] = {'seconds': time.perf_counter()-start,
                            'observed_seat_frames': sum(len(t['frames']) for t in tracks.values()),
                            'audit': audit(tracks, detections, annotation)}
            np.savez_compressed(args.out / f'{segment}-{name}.npz',
                                **{f'{i}_{k}': v for i,t in tracks.items() for k,v in t.items()})
        report['segments'][segment] = result
        print(segment, result, flush=True)
    (args.out / 'comparison.json').write_text(json.dumps(report, indent=2)+'\n')

if __name__ == '__main__': main()
