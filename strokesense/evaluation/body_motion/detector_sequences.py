"""Compare candidate backbones on identical 20-second rowing windows locally."""
from detector_candidates import ROOT, detector
import json
import hashlib
import time
from pathlib import Path
from strokesense.pose import run_video, save_detections, load_detections, crew_tracks, PoseResult
from strokesense import kinematics, strokes


def main():
    root=ROOT/'results/body-motion-evaluation/detector-candidates'
    manifest=json.loads((root/'manifest.json').read_text())
    summaries={}
    ledger_path=root/'sequence-cache-hashes.json'
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    for size in ['n','s','m']:
        model=detector(ROOT/'models'/f'yolo11{size}-pose.onnx')
        for stem in ['IMG_9673','IMG_9674']:
            target=root/f'{stem}-{size}-sequence.npz'
            started=time.perf_counter()
            reused=target.exists()
            if reused:
                if ledger.get(target.name)!=hashlib.sha256(target.read_bytes()).hexdigest():
                    raise ValueError('unverified or changed sequence cache')
                detections,meta=load_detections(target)
            else:
                source=ROOT.parent.parent/'test-footage'/f'{stem}.MP4'
                detections,meta=run_video(source,model,tiles=manifest['clips'][stem]['tiles'],duration=20.,target_fps=15.,
                   progress=lambda i,n:print(size,stem,i,n,flush=True))
                save_detections(target,detections,meta)
                ledger[target.name]=hashlib.sha256(target.read_bytes()).hexdigest()
                ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
            elapsed=time.perf_counter()-started
            tracks,direction,count=crew_tracks(detections,meta['fps'],expected_seats=8)
            pose=PoseResult(fps=meta['fps'],n_frames=len(detections),width=meta['width'],height=meta['height'],tracks=tracks,start=meta['start'],stride=meta['stride'])
            rows=[]
            for seat in sorted(tracks):
                k=kinematics.build(pose.dense(seat),meta['fps']);cycles,_=strokes.analyse(k)
                rows.append({'seat':seat+1,'track_frames':len(tracks[seat]['frames']),
                    'visible_frames':int(k.visible.sum()),'rejected_points':sum(int(m.sum()) for m in k.rejected.values()),
                    'cycles':len(cycles),'rates':[s.rate for s in cycles]})
            summaries[f'{stem}-{size}']={'seconds':elapsed,'cache_reused':reused,'extraction_seconds':None if reused else elapsed,'timing_version':getattr(strokes,'VERSION','legacy'),'rows':rows}
            (root/'sequence-diagnostics.json').write_text(json.dumps(summaries,indent=2)+'\n')
            print('FINISHED',size,stem,round(elapsed,1),rows,flush=True)

if __name__=='__main__':main()
