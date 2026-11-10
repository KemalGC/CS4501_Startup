"""Measure frame quantization versus fractional timing on analytic cycles."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_fractional_timing import sinusoid
from strokesense import strokes

rows=[]
for fps in [10,15,30]:
    for rate in [18.7,22.3,31.1,43.7]:
        cycles,_=strokes.analyse(sinusoid(fps,rate))
        old=np.array([60*fps/(s.next_catch-s.catch) for s in cycles])
        new=np.array([s.rate for s in cycles])
        rows.append({'fps':fps,'true_rate':rate,'cycles':len(cycles),
                     'frame_rate_rmse':float(np.sqrt(np.mean((old-rate)**2))),
                     'fractional_rate_rmse':float(np.sqrt(np.mean((new-rate)**2)))})
result={'scope':'Analytic sinusoidal body motion with exact period; timing quantization only, not real catch/contact accuracy.', 'cases':rows}
p=ROOT/'results/stroke-timing-evaluation';p.mkdir(parents=True,exist_ok=True)
(p/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
Path(__file__).with_name('results.json').write_text(json.dumps(result,indent=2)+'\n')
print('Mean SPM RMSE:',*(float(np.mean([r[k] for r in rows])) for k in ['frame_rate_rmse','fractional_rate_rmse']))
