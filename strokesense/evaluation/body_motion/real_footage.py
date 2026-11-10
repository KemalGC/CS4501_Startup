"""Motion diagnostics on real cached tracks; smoothness is not accuracy."""
from compare import ROOT, baseline
import json
from pathlib import Path
import sys
import numpy as np
from strokesense import kinematics, strokes


def main():
    track_root=ROOT/'results/model-tracking-evaluation'
    metadata=json.loads((track_root/'comparison.json').read_text())['segments']
    result={'scope':'Same real detections/identities, old versus revised body conditioning. No independent joint-position labels. Jitter diagnostics are not accuracy metrics.','segments':{}}
    for name,meta in metadata.items():
        z=np.load(track_root/f'{name}-candidate.npz');rows=[]
        for seat in range(8):
            if f'{seat}_frames' not in z:continue
            kp=np.zeros((meta['sampled_frames'],17,3));kp[z[f'{seat}_frames']]=z[f'{seat}_kpts']
            row={'seat':seat+1}
            for label,module in [('baseline',baseline),('candidate',kinematics)]:
                k=module.build(kp,meta['fps']);cycles,_=strokes.analyse(k)
                row[label]={'side':k.side,'visible_frames':int(k.visible.sum()),'cycles':len(cycles),
                  'rejected':{j:int(a.sum()) for j,a in getattr(k,'rejected',{}).items()},
                  'median_rate':float(np.median([s.rate for s in cycles])) if cycles else None}
            rows.append(row)
        result['segments'][name]=rows
        print(name, {label:{'visible':sum(r[label]['visible_frames'] for r in rows),
              'cycles':sum(r[label]['cycles'] for r in rows),
              'rejected':sum(sum(r[label]['rejected'].values()) for r in rows)} for label in ['baseline','candidate']},flush=True)
        z.close()
    out=ROOT/'results/body-motion-evaluation';out.mkdir(parents=True,exist_ok=True)
    (out/'real-footage.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
