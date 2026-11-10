"""Local paired inference experiment; never changes the application default model."""
import hashlib
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from strokesense.pose import PoseDetector, auto_tiles


def detector(path):
    # Keep backend/thread settings identical across model capacities.
    options=ort.SessionOptions();options.intra_op_num_threads=4
    d=PoseDetector.__new__(PoseDetector)
    d.sess=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
    d.inp=d.sess.get_inputs()[0].name;d.size=640;d.conf=.25;d.iou=.5
    return d


def main():
    output=ROOT/'results/body-motion-evaluation/detector-candidates'
    output.mkdir(parents=True,exist_ok=True)
    models={s:detector(ROOT/'models'/f'yolo11{s}-pose.onnx') for s in ['n','s','m']}
    manifest={'scope':'Paired local pose inference on identical source frames, fixed nano-derived tiles and CPU backend. Model capacity is an experiment, not an accuracy conclusion.','clips':{}}
    for stem in ['IMG_9673','IMG_9674']:
        source=ROOT.parent.parent/'test-footage'/f'{stem}.MP4'
        cap=cv2.VideoCapture(str(source));fps=cap.get(cv2.CAP_PROP_FPS)
        tiles=auto_tiles(source,models['n'],0.,fps,1920,duration=20.)
        frames=[int(round(t*fps)) for t in [0.,2.,3.5,4.,6.,8.,10.,12.,14.,16.,18.]]
        clip={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'fps':fps,
              'tiles':tiles,'frames':frames,'models':{s:{'seconds':0.,'detections':0} for s in models}}
        for fi in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES,fi);ok,im=cap.read()
            if not ok:raise ValueError('source decode failed')
            if im.shape[1]>1920:im=cv2.resize(im,(1920,round(im.shape[0]*1920/im.shape[1])))
            cv2.imwrite(str(output/f'{stem}-{fi}-source.jpg'),im)
            for size,model in models.items():
                before=time.perf_counter();b,s,k=model(im,tiles=tiles)
                clip['models'][size]['seconds']+=time.perf_counter()-before
                clip['models'][size]['detections']+=len(b)
                np.savez_compressed(output/f'{stem}-{fi}-{size}.npz',boxes=b,scores=s,keypoints=k)
            print(stem,fi,flush=True)
        cap.release();manifest['clips'][stem]=clip
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':main()
