"""Replay approximate assistant arm labels; not independent ground truth."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
root=ROOT/'results/body-motion-evaluation/detector-candidates'
labels=json.loads(Path(__file__).with_name('approximate_joint_labels.json').read_text())
result={'provenance':labels['provenance'],'review_tolerance_pixels':labels['uncertainty_source_pixels'],'cases':[]}
for case in labels['cases']:
    image=root/f"{case['source']}-{case['source_frame']}-source.jpg"
    if hashlib.sha256(image.read_bytes()).hexdigest()!=case['source_sha256']:
        raise ValueError('source image does not match labels')
    target=np.array([case['joints'][j] for j in ['shoulder','elbow','wrist']])
    a,b,c,d=case['crop_xyxy'];centre=np.array([(a+c)/2,(b+d)/2])
    for model in ['n','s','m']:
        with np.load(root/f"{case['source']}-{case['source_frame']}-{model}.npz") as z:
            boxes=z['boxes'];k=z['keypoints']
            j=np.linalg.norm((boxes[:,:2]+boxes[:,2:])/2-centre,axis=1).argmin()
            errors=np.linalg.norm(k[j,[6,8,10],:2]-target,axis=1)
            result['cases'].append({'case':case['case'],'model':model,'error_pixels':errors.tolist(),
                'confidence':k[j,[6,8,10],2].tolist(),
                'excess_over_review_tolerance':np.maximum(errors-result['review_tolerance_pixels'],0).tolist()})
for model in ['n','s','m']:
    errors=np.array([r['error_pixels'] for r in result['cases'] if r['model']==model])
    print(model,'mean pixel error',np.round(errors.mean(0),2),'overall',round(errors.mean(),2))
output=ROOT/'results/body-motion-evaluation/joint-audit';output.mkdir(parents=True,exist_ok=True)
(output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
