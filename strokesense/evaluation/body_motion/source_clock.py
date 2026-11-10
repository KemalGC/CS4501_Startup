"""Audit decoded frame timestamps against the nominal source-frame clock."""
import json
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
rows=[]
for path in sorted((ROOT.parent.parent/'test-footage').glob('*.MP4')):
    cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS);timestamps=[]
    if not cap.isOpened():raise ValueError('cannot open source')
    while True:
        ok,_=cap.read()
        if not ok:break
        timestamps.append(cap.get(cv2.CAP_PROP_POS_MSEC)/1000)
    cap.release();timestamps=np.asarray(timestamps);deltas=np.diff(timestamps)
    rows.append({'source':path.name,'fps':fps,'frames':len(timestamps),
        'monotonic':bool((deltas>0).all()),
        'frame_delta_percentiles':np.percentile(deltas,[0,50,95,100]).tolist(),
        'max_nominal_clock_error_seconds':float(np.max(np.abs(timestamps-np.arange(len(timestamps))/fps)))})
output=ROOT/'results/body-motion-evaluation/source-clock.json';output.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
