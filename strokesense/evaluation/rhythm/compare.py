"""Compare rhythm/stroke selection with source-time gaps preserved."""
from pathlib import Path
import importlib.util,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import kinematics,strokes
spec=importlib.util.spec_from_file_location('strokesense.rhythm_baseline',Path(__file__).with_name('baseline_strokes.py'))
baseline=importlib.util.module_from_spec(spec);sys.modules[spec.name]=baseline;spec.loader.exec_module(baseline)
root=ROOT/'results/model-tracking-evaluation';meta=json.loads((root/'comparison.json').read_text())['segments'];result={}
for segment,m in meta.items():
    z=np.load(root/f'{segment}-candidate.npz');rows=[]
    for seat in range(8):
        if f'{seat}_frames' not in z:continue
        kp=np.zeros((m['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts'];k=kinematics.build(kp,m['fps'])
        row={'seat':seat+1}
        for name,module in [('baseline',baseline),('candidate',strokes)]:
            s,_,_=module.find_strokes(k);row[name]={'cycles':len(s),'events':[list(t) for t in s]}
        rows.append(row)
    result[segment]=rows;z.close()
    print(segment,*(sum(r[name]['cycles'] for r in rows) for name in ['baseline','candidate']),flush=True)
out=ROOT/'results/rhythm-evaluation';out.mkdir(parents=True,exist_ok=True)
(out/'comparison.json').write_text(json.dumps({'scope':'Real cached tracks, same body conditioning. Cycle counts are diagnostics, not labeled event accuracy.','segments':result},indent=2)+'\n')
