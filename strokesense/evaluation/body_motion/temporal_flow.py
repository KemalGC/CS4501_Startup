"""Offline neighboring-frame pose consensus; never changes production inference.

Warp independent neighboring detections into the target frame with bidirectional
Lucas-Kanade flow. Reject weak/mismatched identities and poor round trips. Keep
current coordinates if fewer than three independently observed estimates survive.
"""
from detector_candidates import ROOT,detector
from pathlib import Path
import cv2,json,numpy as np
root=ROOT/'results/body-motion-evaluation/detector-candidates'
out=ROOT/'results/body-motion-evaluation/temporal-flow';out.mkdir(parents=True,exist_ok=True)
labels=json.loads(Path(__file__).with_name('approximate_joint_labels.json').read_text())
manifest=json.loads((root/'manifest.json').read_text())
model=detector(ROOT/'models/yolo11n-pose.onnx');results=[];sheets=[]
params=dict(winSize=(15,15),maxLevel=2,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
for case in labels['cases']:
    cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage'/f"{case['source']}.MP4"))
    frames={}
    for delta in [-2,-1,0,1,2]:
        cap.set(cv2.CAP_PROP_POS_FRAMES,case['source_frame']+delta);ok,im=cap.read()
        if not ok:raise ValueError('decode failed')
        frames[delta]=im
    cap.release();frame=frames[0];gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    a,b,c,d=case['crop_xyxy'];centre=np.array([(a+c)/2,(b+d)/2])
    with np.load(root/f"{case['source']}-{case['source_frame']}-n.npz") as z:
        j=np.linalg.norm((z['boxes'][:,:2]+z['boxes'][:,2:])/2-centre,axis=1).argmin();base=z['keypoints'][j].copy()
    torso=np.linalg.norm(base[6,:2]-base[12,:2]);votes=[base[:,:2].copy()];support=[base[:,2]>=.35]
    for delta in [-2,-1,1,2]:
        near=frames[delta];ngray=cv2.cvtColor(near,cv2.COLOR_BGR2GRAY)
        predicted,status,_=cv2.calcOpticalFlowPyrLK(gray,ngray,base[:,None,:2].astype(np.float32),None,**params)
        boxes,scores,kk=model(near,tiles=manifest['clips'][case['source']]['tiles'])
        if not len(kk) or not status[12,0]:continue
        distances=np.linalg.norm(kk[:,12,:2]-predicted[12,0],axis=1);idx=distances.argmin()
        if distances[idx]>.6*torso or kk[idx,12,2]<.35:continue
        k=kk[idx];points=k[:,None,:2].astype(np.float32)
        forward,ok1,err=cv2.calcOpticalFlowPyrLK(ngray,gray,points,None,**params)
        backward,ok2,_=cv2.calcOpticalFlowPyrLK(gray,ngray,forward,None,**params)
        good=(ok1[:,0]>0)&(ok2[:,0]>0)&(err[:,0]<20)&(np.linalg.norm(backward[:,0]-points[:,0],axis=1)<1)&(k[:,2]>=.35)
        votes.append(forward[:,0]);support.append(good)
    votes=np.array(votes);support=np.array(support);candidate=base.copy()
    for joint in range(17):
        if support[:,joint].sum()>=3:candidate[joint,:2]=np.median(votes[support[:,joint],joint],axis=0)
    truth=np.array([case['joints'][j] for j in ['shoulder','elbow','wrist']]);row=[]
    for name,k in [('base',base),('flow',candidate)]:
        errors=np.linalg.norm(k[[6,8,10],:2]-truth,axis=1)
        results.append({'case':case['case'],'variant':name,'errors':errors.tolist(),'support':support[:,[6,8,10]].sum(0).tolist()})
        im=frame.copy()
        for u,v in [(6,8),(8,10),(6,12),(12,14)]:cv2.line(im,tuple(np.rint(k[u,:2]).astype(int)),tuple(np.rint(k[v,:2]).astype(int)),(0,255,0),1)
        for j in [6,8,10,12,14]:cv2.circle(im,tuple(np.rint(k[j,:2]).astype(int)),2,(0,0,255),-1)
        crop=cv2.resize(im[b:d,a:c],(480,360));cv2.putText(crop,f"Case {case['case']} / {name}",(8,25),0,.7,(255,255,255),2);row.append(crop)
    sheets.append(np.hstack(row))
    np.savez_compressed(out/f"case-{case['case']}.npz",base=base,candidate=candidate,votes=votes,support=support)
    print('case',case['case'],'complete',flush=True)
cv2.imwrite(str(out/'comparison.jpg'),np.vstack(sheets))
(out/'results.json').write_text(json.dumps({'scope':labels['provenance'],'review_tolerance_pixels':labels['uncertainty_source_pixels'],'cases':results},indent=2)+'\n')
for name in ['base','flow']:
    errors=np.array([r['errors'] for r in results if r['variant']==name]);print(name,errors.mean(0),errors.mean(),flush=True)
