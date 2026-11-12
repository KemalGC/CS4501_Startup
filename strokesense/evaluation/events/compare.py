"""Paired phase selection experiment: identical tracks and body signals."""
from pathlib import Path
import importlib.util,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import kinematics
modules={}
for name in ['baseline','candidate']:
    spec=importlib.util.spec_from_file_location('strokesense.event_'+name,Path(__file__).with_name(name+'_strokes.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);modules[name]=module
root=ROOT/'results/model-tracking-evaluation';meta=json.loads((root/'comparison.json').read_text())['segments'];result={}
for segment,m in meta.items():
    rows=[]
    with np.load(root/f'{segment}-candidate.npz') as z:
        for seat in range(8):
            if f'{seat}_frames' not in z:continue
            kp=np.zeros((m['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts'];k=kinematics.build(kp,m['fps'])
            row={'seat':seat}
            for name,module in modules.items():
                ss,_,_=module.find_strokes(k);row[name]=[list(s) for s in ss]
            rows.append(row)
    result[segment]=rows
    print(segment,*(sum(len(r[name]) for r in rows) for name in modules),flush=True)
Path(__file__).with_name('comparison.json').write_text(json.dumps({'scope':'Diagnostic event changes, not labeled accuracy. Candidate is experimental only.','segments':result},indent=2)+'\n')
