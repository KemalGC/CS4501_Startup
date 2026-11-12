"""Review largest finish changes on the second source video; source pixels only."""
from pathlib import Path
import sys,json
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import kinematics
meta=json.loads((ROOT/'results/model-tracking-evaluation/comparison.json').read_text())['segments']
comparison=json.loads(Path(__file__).with_name('comparison.json').read_text())['segments']
out=ROOT/'results/event-evaluation/additional';out.mkdir(parents=True,exist_ok=True)
manifest=[]
for case,(segment,seat,catch) in enumerate([('9674-boat1',7,130),('9674-boat1',2,54),('9674-boat1',0,194),('9674-boat2',3,82)]):
    m=meta[segment];r=next(r for r in comparison[segment] if r['seat']==seat)
    old=next(s for s in r['baseline'] if s[0]==catch);new=next(s for s in r['candidate'] if s[0]==catch)
    with np.load(ROOT/f'results/model-tracking-evaluation/{segment}-candidate.npz') as z:
        kp=np.zeros((m['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts']
    k=kinematics.build(kp,m['fps']);cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage/IMG_9674.MP4'))
    offset=int(m['start']*cap.get(cv2.CAP_PROP_FPS));canvas=np.full((2*280,7*320,3),245,np.uint8)
    ledger={'case':case,'segment':segment,'slot':seat,'catch':catch,'baseline_finish':old[1],'candidate_finish':new[1],'frames':[], 'measurements':[]}
    for fi in range(min(old[1],new[1])-3,max(old[1],new[1])+4):
        values={name:float(k.angles[name][fi]) for name in ['trunk','elbow','thigh']}
        values.update(handle=float(k.handle[fi]),shoulder_relative_hand=float((k.uv['wrist'][fi]-k.uv['shoulder'][fi])[0]))
        ledger['measurements'].append({'analysis_frame':fi,'values':{name:value if np.isfinite(value) else None for name,value in values.items()},'confidence':{j:float(k.conf[j][fi]) for j in ['hip','shoulder','elbow','wrist']},'observed':{j:bool(k.observed[j][fi]) for j in ['hip','shoulder','elbow','wrist']}})
    for ri,(name,centre) in enumerate([('baseline',old[1]),('candidate',new[1])]):
        for ci,fi in enumerate(range(centre-3,centre+4)):
            sf=offset+fi*2;cap.set(cv2.CAP_PROP_POS_FRAMES,sf);ok,im=cap.read()
            if not ok:raise RuntimeError('decode failed')
            hip=k.px['hip'][fi];assert np.isfinite(hip).all()
            w=max(180,round(k.scale_px*4.5));h=round(w*.75)
            x=max(0,min(im.shape[1]-w,round(hip[0]-w*.5)));y=max(0,min(im.shape[0]-h,round(hip[1]-h*.7)))
            crop=cv2.resize(im[y:y+h,x:x+w],(320,240));canvas[ri*280+35:ri*280+275,ci*320:(ci+1)*320]=crop
            label=f'{name} {fi-centre:+d} {m["start"]+fi/m["fps"]:.3f}s'
            cv2.putText(canvas,label,(ci*320+3,ri*280+24),0,.6,(0,0,200) if ci==3 else (0,0,0),1,cv2.LINE_AA)
            ledger['frames'].append({'variant':name,'analysis_frame':fi,'source_frame':sf,'crop':[x,y,x+w,y+h]})
    cv2.imwrite(str(out/f'case-{case}.jpg'),canvas);manifest.append(ledger);cap.release()
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
