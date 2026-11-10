"""Source-pixel contact sheets around detected events; no invented pose labels."""
from pathlib import Path
import sys,json,importlib.util
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import kinematics
spec=importlib.util.spec_from_file_location('strokesense.event_review_baseline',Path(__file__).with_name('baseline_strokes.py'))
strokes=importlib.util.module_from_spec(spec);sys.modules[spec.name]=strokes;spec.loader.exec_module(strokes)
out=ROOT/'results/event-evaluation';out.mkdir(parents=True,exist_ok=True)
meta=json.loads((ROOT/'results/model-tracking-evaluation/comparison.json').read_text())['segments']
segment='9673-boat1';m=meta[segment];seat=0
with np.load(ROOT/f'results/model-tracking-evaluation/{segment}-candidate.npz') as z:
    kp=np.zeros((m['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts']
k=kinematics.build(kp,m['fps']);found,_=strokes.analyse(k)
cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage/IMG_9673.MP4'))
selected=found[:2] if len(sys.argv)<2 else [found[int(sys.argv[1])]]
suffix="" if len(sys.argv)<2 else "-cycle"+sys.argv[1]
events=[]
for s in selected:
    events.extend([('catch',s.catch),('finish',s.finish),
                   ('hand min',s.catch+int(np.argmin(k.handle[s.catch:s.next_catch+1])))])
canvas=np.full((len(events)*220,9*240,3),245,np.uint8);manifest=[]
for ri,(event,centre) in enumerate(events):
    frames=[]
    for ci,fi in enumerate(range(centre-4,centre+5)):
        cap.set(cv2.CAP_PROP_POS_FRAMES,fi*2);ok,im=cap.read()
        if not ok:raise RuntimeError('decode')
        hip=np.nan_to_num(k.px['hip'][fi],nan=0).astype(int)
        x=max(0,min(im.shape[1]-160,hip[0]-80));y=max(0,min(im.shape[0]-120,hip[1]-85))
        crop=cv2.resize(im[y:y+120,x:x+160],(240,180))
        canvas[ri*220+35:ri*220+215,ci*240:(ci+1)*240]=crop
        label=f'{event} {fi-centre:+d} {fi/m["fps"]:.3f}s'
        cv2.putText(canvas,label,(ci*240+3,ri*220+24),cv2.FONT_HERSHEY_SIMPLEX,.48,(0,0,200) if ci==4 else (0,0,0),1,cv2.LINE_AA)
        frames.append({'analysis_frame':fi,'source_frame':fi*2,'crop':[int(v) for v in (x,y,x+160,y+120)]})
    manifest.append({'event':event,'detected_frame':centre,'frames':frames})
cap.release();cv2.imwrite(str(out/f'9673-seat1-events{suffix}.jpg'),canvas)
(out/f'9673-seat1-events{suffix}.json').write_text(json.dumps(manifest,indent=2)+'\n')
print([(s.catch,s.finish,s.next_catch) for s in found])
