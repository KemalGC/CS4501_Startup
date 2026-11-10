"""Separate duration-dependent crop selection from the cached torso trajectory."""
from detector_candidates import ROOT,detector
from strokesense.pose import auto_tiles,PoseDetector
import cv2,json,numpy as np
from pathlib import Path
source=ROOT.parent.parent/'test-footage/IMG_9674.MP4'
model=detector(ROOT/'models/yolo11n-pose.onnx');cap=cv2.VideoCapture(str(source));fps=cap.get(cv2.CAP_PROP_FPS)
manifest=json.loads((ROOT/'results/body-motion-evaluation/detector-candidates/manifest.json').read_text())
tiles={'cpu20':manifest['clips']['IMG_9674']['tiles'],'cpu21':auto_tiles(source,model,0.,fps,1920,duration=21.)}
core=PoseDetector(threads=4);tiles['configured21']=auto_tiles(source,core,0.,fps,1920,duration=21.)
z=np.load(ROOT/'results/model-tracking-evaluation/9674-boat1-candidate.npz');lookup={int(f):k for f,k in zip(z['0_frames'],z['0_kpts'])};z.close()
results=[]
for fi in [208,209,210,211,212,213]:
    cap.set(cv2.CAP_PROP_POS_FRAMES,fi*2);ok,frame=cap.read()
    if not ok:raise RuntimeError('decode failed')
    ref=lookup[fi];shoulder=ref[[5,6],:2].mean(0);variants={'cached':ref}
    for name,crops in tiles.items():
        bb,ss,kk=(core if name=='configured21' else model)(frame,tiles=crops)
        idx=np.linalg.norm(kk[:,[5,6],:2].mean(1)-shoulder,axis=1).argmin();variants[name]=kk[idx]
    for name,k in variants.items():
        d=(k[6,:2]-k[12,:2])*[1,-1]
        results.append({'frame':fi,'variant':name,'hip':k[12].tolist(),'trunk_angle':float(np.degrees(np.arctan2(d[0],d[1])))})
cap.release();out=ROOT/'results/body-motion-evaluation/torso-candidates'
(out/'replay.json').write_text(json.dumps({'tiles':tiles,'results':results},indent=2)+'\n')
for r in results:print(r['frame'],r['variant'],round(r['trunk_angle'],1),[round(v,1) for v in r['hip'][:2]],flush=True)
