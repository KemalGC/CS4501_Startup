"""Opt-in same-prediction comparison; development footage, not a held-out metric.

The eight-video reference below was selected by assistant visual inspection at
source frame 99 (3.96s), excluding the leftmost coxswain. It is NOT a human
identity annotation or measured identity accuracy. Amsterdam is detection-only:
its multiple crews must not be combined into an automatically selected eight.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense.pose import PoseDetector
from strokesense import multiframe
from strokesense.pose_merge import merge_refined_detections
from strokesense.selection import locked_tracks, SelectionError
from real_video_smoke import digest

EIGHT_SEEDS = [[.21390,.57444],[.31175,.58168],[.41178,.58208],[.50529,.59015],
               [.60043,.58659],[.69740,.60443],[.80052,.60922],[.90383,.61611]]


def legacy_merge(b,s,k):
    rects=np.c_[b[:,:2],b[:,2:]-b[:,:2]].tolist()
    idx=np.asarray(cv2.dnn.NMSBoxes(rects,s.tolist(),.25,.5),int).reshape(-1)
    return b[idx],s[idx],k[idx]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--profile',choices=['eight','amsterdam'],required=True)
    a=p.parse_args()
    if not a.model.is_file() or not a.video.is_file():p.error('explicit local inputs required')
    a.out.mkdir(parents=True,exist_ok=True)
    detector=PoseDetector(a.model); cap=cv2.VideoCapture(str(a.video));cv2.setNumThreads(1)
    fps=cap.get(cv2.CAP_PROP_FPS);total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not cap.isOpened() or not 0<fps<=240:raise ValueError('invalid_media')
    stride=max(1,round(fps/15));indices=list(range(int(3*fps),min(total,int(5*fps)),stride))
    series={'before':[],'after':[]};records=[];images={};raw_data={};began=time.monotonic()
    try:
        for fi,index in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=cap.read()
            if not ok:raise ValueError('decode_failed')
            h,w=image.shape[:2]; raw=[]
            def capture(b,s,k):
                raw.append((b.copy(),s.copy(),k.copy()))
                return legacy_merge(b,s,k)
            with patch.object(multiframe,'merge_refined_detections',side_effect=capture):
                before=multiframe.refined_detections(image,detector)
            if not raw:raw.append(before)
            after=merge_refined_detections(*raw[0])
            for name,result in [('before',before),('after',after)]:
                series[name].append((result[0],result[2]))
            for name,value in zip(('boxes','scores','keypoints'),raw[0]):raw_data[f'{fi}_{name}']=value
            records.append({'source_frame':index,'seconds':index/fps,
                'before':len(before[0]),'after':len(after[0])})
            if fi in (0,len(indices)//2,len(indices)-1):images[fi]=image.copy()
            print(json.dumps(records[-1]),flush=True)
    finally:cap.release()
    summary={'real_model_inference':True,'human_labels':False,'accuracy':'unmeasured',
        'source_sha256':digest(a.video),'model_sha256':digest(a.model),'sampled_frames':len(indices),
        'seconds_window':[3,5],'frames':records,'tracking':{}}
    for name,dets in series.items():
        tracks={}
        if a.profile=='eight':
            selected={'version':2,'reference_seconds':.96,'roi':[0,0,1,1],
                      'seeds':EIGHT_SEEDS,'confirmed_same_boat':True}
            try:
                tracks=locked_tracks(dets,{'width':w,'height':h,'fps':fps/stride},selected)
                summary['tracking'][name]={'observed_by_slot':[len(tracks[i]['frames']) for i in range(8)],
                    'total_slot_frames':8*len(indices),'identity_accuracy':'unmeasured',
                    'reference':'assistant visual selection at source frame 99; not human ground truth'}
            except SelectionError as exc:summary['tracking'][name]={'error':str(exc)}
        else:summary['tracking'][name]={'state':'not_run_multiple_unconfirmed_crews'}
        for fi,image in images.items():
            canvas=image.copy();boxes,_=dets[fi]
            for i,b in enumerate(boxes):
                x0,y0,x1,y1=np.round(b).astype(int)
                cv2.rectangle(canvas,(x0,y0),(x1,y1),(0,180,255),2)
                cv2.putText(canvas,f'D{i+1}',(x0,max(20,y0-3)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,180,255),2)
            for i,t in tracks.items():
                match=np.flatnonzero(t['frames']==fi)
                if len(match):
                    x,y=np.round(t['boxes'][match[0],:2]).astype(int)
                    cv2.putText(canvas,f'S{i+1}',(x,y+20),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,200,0),2)
            cv2.imwrite(str(a.out/f'{fi:03d}-{name}.jpg'),canvas)
    summary['elapsed_seconds']=time.monotonic()-began
    np.savez_compressed(a.out/'real_detections.npz',**raw_data)
    (a.out/'comparison.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in summary.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
