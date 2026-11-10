"""Replay identical tracked motion through old and candidate crew association."""
from pathlib import Path
import importlib.util,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import kinematics,strokes,crew
spec=importlib.util.spec_from_file_location('sync_baseline',Path(__file__).with_name('baseline.py'))
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
root=ROOT/'results/model-tracking-evaluation';meta=json.loads((root/'comparison.json').read_text())['segments'];result={}
for segment,m in meta.items():
    rows=[]
    with np.load(root/f'{segment}-candidate.npz') as z:
        for seat in range(8):
            if f'{seat}_frames' not in z:continue
            kp=np.zeros((m['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts']
            k=kinematics.build(kp,m['fps']);s,_=strokes.analyse(k)
            rows.append(crew.Rower(tid=seat,seat=str(seat+1),k=k,strokes=s))
    before=baseline.crew_sync(rows,m['fps']);after=crew.crew_sync(rows,m['fps'])
    result[segment]={'baseline':before,'candidate':after}
    print(segment,'spread_ms',before.get('crew_spread_ms'),after.get('crew_spread_ms'),'supported_events',len(after['matched_events']),flush=True)
Path(__file__).with_name('results.json').write_text(json.dumps({'scope':'Same real tracks and catch detections. Changes are diagnostic, not independently labeled accuracy.','segments':result},indent=2)+'\n')
