"""Offline horizontal-reflection equivariance audit with anatomical remapping."""
from detector_candidates import ROOT,detector
from pathlib import Path
import cv2,json,numpy as np
root=ROOT/'results/body-motion-evaluation/detector-candidates'
out=ROOT/'results/body-motion-evaluation/mirror-consistency';out.mkdir(parents=True,exist_ok=True)
labels=json.loads(Path(__file__).with_name('approximate_joint_labels.json').read_text())
manifest=json.loads((root/'manifest.json').read_text())
model=detector(ROOT/'models/yolo11n-pose.onnx');results=[];sheets=[]
flip=np.array([0,2,1,4,3,6,5,8,7,10,9,12,11,14,13,16,15])
for case in labels['cases']:
    cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage'/f"{case['source']}.MP4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES,case['source_frame']);ok,frame=cap.read();cap.release()
    if not ok:raise ValueError('decode failed')
    width=frame.shape[1];a,b,c,d=case['crop_xyxy'];centre=np.array([(a+c)/2,(b+d)/2])
    with np.load(root/f"{case['source']}-{case['source_frame']}-n.npz") as z:
        j=np.linalg.norm((z['boxes'][:,:2]+z['boxes'][:,2:])/2-centre,axis=1).argmin();base=z['keypoints'][j].copy()
    tiles=[(width-x1,y,width-x,y1) for x,y,x1,y1 in manifest['clips'][case['source']]['tiles']]
    boxes,scores,keypoints=model(np.ascontiguousarray(frame[:,::-1]),tiles=tiles)
    keypoints=keypoints[:,flip].copy();keypoints[:,:,0]=width-1-keypoints[:,:,0]
    distance=np.linalg.norm(keypoints[:,12,:2]-base[12,:2],axis=1);idx=distance.argmin()
    if distance[idx]>.6*np.linalg.norm(base[6,:2]-base[12,:2]):raise ValueError('ambiguous mirrored identity')
    mirrored=keypoints[idx];mean=base.copy();both=(base[:,2]>=.35)&(mirrored[:,2]>=.35)
    mean[both,:2]=(base[both,:2]+mirrored[both,:2])/2
    target=np.array([case['joints'][j] for j in ['shoulder','elbow','wrist']]);row=[]
    for name,k in [('base',base),('mirror',mirrored),('mean',mean)]:
        errors=np.linalg.norm(k[[6,8,10],:2]-target,axis=1)
        results.append({'case':case['case'],'variant':name,'errors':errors.tolist(),'confidence':k[[6,8,10],2].tolist()})
        im=frame.copy()
        for u,v in [(6,8),(8,10),(6,12),(12,14)]:cv2.line(im,tuple(np.rint(k[u,:2]).astype(int)),tuple(np.rint(k[v,:2]).astype(int)),(0,255,0),1)
        for j in [6,8,10,12,14]:cv2.circle(im,tuple(np.rint(k[j,:2]).astype(int)),2,(0,0,255),-1)
        crop=cv2.resize(im[b:d,a:c],(400,300));cv2.putText(crop,f"Case {case['case']} / {name}",(6,25),0,.6,(255,255,255),2);row.append(crop)
    sheets.append(np.hstack(row));np.savez_compressed(out/f"case-{case['case']}.npz",base=base,mirrored=mirrored,mean=mean)
cv2.imwrite(str(out/'comparison.jpg'),np.vstack(sheets))
(out/'results.json').write_text(json.dumps({'scope':labels['provenance'],'review_tolerance_pixels':labels['uncertainty_source_pixels'],'cases':results},indent=2)+'\n')
for name in ['base','mirror','mean']:
    errors=np.array([r['errors'] for r in results if r['variant']==name]);print(name,errors.mean(0),errors.mean(),flush=True)
