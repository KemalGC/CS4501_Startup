"""Compare fresh full-rate and half-rate processing; no rate is ground truth."""
from pathlib import Path
import json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense.pose import load_detections
roots={name:ROOT/'results'/directory/'IMG_9673--ebc59e58c20a888dfc7c' for name,directory in [('half','final-pipeline-evaluation'),('full','full-rate-evaluation')]}
metrics={name:json.loads((root/'metrics.json').read_text()) for name,root in roots.items()}
caches={name:load_detections(root/'detections.npz') for name,root in roots.items()}
summary={}
for name,data in metrics.items():
    summary[name]={'fps':data['evidence']['fps'],'source_frames':len(caches[name][0]),
        'cycles':sum(len(r['strokes']) for r in data['rowers']),
        'crew_cadence':data['crew_cadence']['rate_spm'],'supported_crew_events':len(data['sync']['matched_events'])}
shared=[]
for half,full in zip(caches['half'][0],caches['full'][0][::2]):
    shared.append(all(a.shape==b.shape and np.array_equal(a,b) for a,b in zip(half,full)))
summary['shared_detection_frames']={'compared':len(shared),'exactly_equal':sum(shared)}
paired=[]
for row in metrics['half']['rowers']:
    other=next(r for r in metrics['full']['rowers'] if r['seat']==row['seat']);used=set();pairs=[]
    for s in row['strokes']:
        choices=[(abs(t['catch_t']/summary['full']['fps']-s['catch_t']/summary['half']['fps']),j,t) for j,t in enumerate(other['strokes']) if j not in used]
        if not choices:continue
        distance,j,t=min(choices)
        if distance>.3:continue
        used.add(j);pairs.append({'half_catch_s':s['catch_t']/summary['half']['fps'],
            'full_catch_s':t['catch_t']/summary['full']['fps'],
            'finish_delta_s':t['finish_t']/summary['full']['fps']-s['finish_t']/summary['half']['fps'],
            'rate_delta_spm':t['rate']-s['rate']})
    paired.append({'seat':row['seat'],'half_cycles':len(row['strokes']),'full_cycles':len(other['strokes']),'pairs':pairs})
result={'scope':'Same source window, default model, fixed CLI settings except analysis fps. Diagnostic agreement only; neither sampling rate is independent ground truth.','summary':summary,'paired_cycles':paired}
Path(__file__).with_name('results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(summary,indent=2))
