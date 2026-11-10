"""Render original/candidate association overlays locally for visual review."""
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strokesense.pose import load_detections


def draw(frame, predictions, fi, width, height, label):
    image = cv2.resize(frame, (960, 540))
    for seat in range(8):
        if f'{seat}_frames' not in predictions: continue
        indices = np.flatnonzero(predictions[f'{seat}_frames'] == fi)
        if not len(indices): continue
        # Repeat the coordinate scale in xyxy order.
        box = predictions[f'{seat}_boxes'][indices[0]] * np.array([960/width,540/height,960/width,540/height])
        x,y,x1,y1 = np.round(box).astype(int)
        cv2.rectangle(image,(x,y),(x1,y1),(0,255,0),2)
        cv2.putText(image,str(seat+1),(x,max(20,y-7)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,255),2)
    cv2.rectangle(image,(0,0),(960,34),(0,0,0),-1)
    cv2.putText(image,label,(12,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caches',type=Path,default=Path('results/tracking-v2'))
    parser.add_argument('--footage',type=Path,default=Path('../../test-footage'))
    parser.add_argument('--results',type=Path,default=Path('results/model-tracking-evaluation'))
    parser.add_argument('--videos',action='store_true')
    args=parser.parse_args()
    labels=json.loads(Path(__file__).with_name('labels.json').read_text())['segments']
    for name,frames in labels.items():
        _,meta=load_detections(next((args.caches/name).glob('*/detections.npz')))
        source=args.footage/f'IMG_{name.split("-")[0]}.MP4'
        cap=cv2.VideoCapture(str(source));source_fps=cap.get(cv2.CAP_PROP_FPS)
        if not cap.isOpened(): raise ValueError(f'Cannot open {source}')
        old=np.load(args.results/f'{name}-baseline.npz');new=np.load(args.results/f'{name}-candidate.npz')
        sheets=[]
        for fi in map(int,frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(meta['start']*source_fps)+fi*meta['stride'])
            ok,image=cap.read()
            if not ok: raise ValueError('Cannot decode audit frame')
            sheets.append(np.hstack([draw(image,pred,fi,meta['width'],meta['height'],f'{name} / frame {fi} / {model}')
                                     for model,pred in [('BASELINE',old),('REVISED',new)]]))
        cv2.imwrite(str(args.results/f'{name}-comparison.jpg'),np.vstack(sheets))
        if args.videos:
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(meta['start']*source_fps))
            count=json.loads((args.results/'comparison.json').read_text())['segments'][name]['sampled_frames']
            writer=cv2.VideoWriter(str(args.results/f'{name}-comparison.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),meta['fps'],(1920,540))
            if not writer.isOpened(): raise ValueError('Video writer unavailable')
            for fi in range(count):
                ok,image=cap.read()
                if not ok: break
                writer.write(np.hstack([draw(image,p,fi,meta['width'],meta['height'],f'{name} / {model}')
                                        for model,p in [('BASELINE',old),('REVISED',new)]]))
                for _ in range(meta['stride']-1): cap.grab()
            writer.release()
        cap.release();old.close();new.close()
        print(name,flush=True)

if __name__=='__main__':main()
