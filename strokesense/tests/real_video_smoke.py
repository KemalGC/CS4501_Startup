"""Opt-in real-video inspection. No downloads, labels, or accuracy claims.

Accepts local files explicitly. Outputs source/model hashes, actual detections,
frame overlays and observation coverage; never counts detections as ground truth.
Do not publish artifacts for private input footage.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.pose import PoseDetector
from strokesense.multiframe import refined_detections
from strokesense.auto_selection import detect_candidates
from strokesense.selection import locked_tracks, SelectionError


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect_video(video, detector, out, *, start=0., seconds=2., fps=15.):
    cap = cv2.VideoCapture(str(video))
    try:
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or not 0 < source_fps <= 240 or total < 1:
            raise ValueError('invalid_media')
        stride = max(1, round(source_fps/fps))
        indices = list(range(int(start*source_fps), min(total, int((start+seconds)*source_fps)), stride))
        if not indices or len(indices) > 90:
            raise ValueError('choose_1_to_90_frames')
        records = []; images = []; detections = []; anchors = []
        began = time.monotonic()
        for n, index in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = cap.read()
            if not ok:
                raise ValueError('decode_failed')
            h,w = image.shape[:2]
            if w > 1920:
                image = cv2.resize(image, (1920, round(h*1920/w)))
            h,w = image.shape[:2]
            t = time.monotonic()
            b,s,k = refined_detections(image, detector)
            candidates = detect_candidates(image, lambda image,tiles=None:(b,s,k))['candidates']
            detections.append((b,k))
            anchors.append(candidates)
            records.append({'source_frame':index,'seconds':index/source_fps,
                'detections':len(b),'usable_candidates':sum(c['seed'] is not None for c in candidates),
                'inference_seconds':time.monotonic()-t,
                'boxes':b.tolist(),'scores':s.tolist(),'candidates':candidates})
            images.append(image)
            print(f'{video.stem}: real frame {n+1}/{len(indices)} detections={len(b)}', flush=True)
        # Inspection only: no auto-selected crew is claimed as operator approved.
        # Use exactly-eight candidate frames for a diagnostic association attempt,
        # labeled unreviewed. The GUI remains explicitly operator-confirmed.
        valid_anchors = [i for i,c in enumerate(anchors) if len(c)==8 and all(p['seed'] is not None for p in c)]
        tracking = {'state':'not_attempted','reason':'no_unambiguous_exactly_eight_reference',
                    'identity_accuracy':'unmeasured','operator_approved':False}
        tracks = {}
        if valid_anchors:
            ai = valid_anchors[len(valid_anchors)//2]
            selected = {'version':2,'reference_seconds':ai/(source_fps/stride),
                'roi':[0,0,1,1],'seeds':[c['seed'] for c in anchors[ai]],'confirmed_same_boat':True}
            try:
                tracks = locked_tracks(detections,{'width':w,'height':h,'fps':source_fps/stride},selected)
                tracking = {'state':'diagnostic_unreviewed','operator_approved':False,
                    'identity_accuracy':'unmeasured','reference_index':ai,
                    'observed_frames_by_slot':[len(tracks[i]['frames']) for i in range(8)],
                    'total_frames':len(indices)}
            except SelectionError as exc:
                tracking['reason']=str(exc)
        out.mkdir(parents=True,exist_ok=True)
        for fi in sorted(set([0,len(indices)//2,len(indices)-1])):
            image = images[fi].copy()
            for i,b in enumerate(records[fi]['boxes']):
                x0,y0,x1,y1 = np.round(b).astype(int)
                cv2.rectangle(image,(x0,y0),(x1,y1),(0,180,255),2)
                cv2.putText(image,f'D{i+1}',(x0,max(20,y0-3)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,180,255),2)
            for slot,tr in tracks.items():
                where=np.flatnonzero(tr['frames']==fi)
                if len(where):
                    b=tr['boxes'][where[0]]; x,y=np.round(b[:2]).astype(int)
                    cv2.putText(image,f'S{slot+1}',(x,y+20),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,200,0),2)
            cv2.imwrite(str(out/f'frame-{fi:03d}.jpg'),image)
        result={'source_sha256':digest(video),'source_fps':source_fps,'source_frames':total,
            'sampled_frames':len(indices),'elapsed_seconds':time.monotonic()-began,
            'real_model_inference':True,'human_annotations':False,'accuracy':'not_measured',
            'tracking':tracking,'frames':records}
        (out/'observations.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        return result
    finally:
        cap.release()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--seconds',type=float,default=2)
    args=p.parse_args()
    if not args.model.is_file() or not args.video.is_file():
        p.error('model and video must already exist; no implicit download')
    cv2.setNumThreads(1)
    detector=PoseDetector(args.model)
    result=inspect_video(args.video,detector,args.out,start=args.start,seconds=args.seconds)
    result['model_sha256']=digest(args.model)
    result['model_family']='YOLO11n-pose'
    (args.out/'observations.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},indent=2))


if __name__=='__main__':
    main()
