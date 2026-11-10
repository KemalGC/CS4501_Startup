"""Inspect crop-level alternatives around a known torso-localization fluctuation."""
from detector_candidates import ROOT,detector
import cv2,json,sys,numpy as np
root=ROOT/'results/body-motion-evaluation/detector-candidates'
out=ROOT/'results/body-motion-evaluation/torso-candidates';out.mkdir(parents=True,exist_ok=True)
model=detector(ROOT/'models/yolo11n-pose.onnx')
tiles=json.loads((root/'manifest.json').read_text())['clips']['IMG_9674']['tiles']
if len(sys.argv)>1:
    tiles=json.loads((out/'replay.json').read_text())['tiles']['cpu21']
    out=out/'duration21';out.mkdir(exist_ok=True)
z=np.load(ROOT/'results/model-tracking-evaluation/9674-boat1-candidate.npz');lookup={int(f):k for f,k in zip(z['0_frames'],z['0_kpts'])};z.close()
cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage/IMG_9674.MP4'));results=[];sheets=[]
for fi in [208,209,210,211,212,213]:
    cap.set(cv2.CAP_PROP_POS_FRAMES,fi*2);ok,frame=cap.read()
    if not ok:raise RuntimeError('decode')
    reference=lookup[fi];shoulder=reference[[5,6],:2].mean(0);candidates=[]
    for ti,(x,y,x1,y1) in enumerate([(0,0,frame.shape[1],frame.shape[0])]+tiles):
        bb,ss,kk=model._infer(frame[y:y1,x:x1]);kk[:,:,:2]+=[x,y]
        for box,score,k in zip(bb,ss,kk):
            if np.linalg.norm(k[[5,6],:2].mean(0)-shoulder)>25:continue
            candidates.append((float(score),ti,k,box.tolist(),[x,y,x1,y1]))
    candidates.sort(key=lambda item:-item[0]);row=[]
    for rank,(score,tile,k,local_box,crop_bounds) in enumerate(candidates):
        torso=np.mean(k[[5,6,11,12],2]);d=(k[6,:2]-k[12,:2])*[1,-1];angle=np.degrees(np.arctan2(d[0],d[1]))
        results.append({'analysis_frame':fi,'rank':rank,'tile':tile,'score':score,'torso_confidence':float(torso),'trunk_angle':float(angle),'hip':k[12].tolist(),'local_box':local_box,'crop_bounds':crop_bounds})
        im=frame.copy()
        for u,v in [(5,11),(6,12),(6,8),(8,10)]:cv2.line(im,tuple(np.rint(k[u,:2]).astype(int)),tuple(np.rint(k[v,:2]).astype(int)),(0,255,0),1)
        for j in [5,6,11,12]:cv2.circle(im,tuple(np.rint(k[j,:2]).astype(int)),2,(0,0,255),-1)
        x=max(0,round(shoulder[0]-100));y=max(0,round(shoulder[1]-40));crop=cv2.resize(im[y:y+170,x:x+220],(440,340))
        cv2.putText(crop,f'f{fi} tile{tile} p{score:.2f} torso{torso:.2f}',(5,22),0,.55,(255,255,255),2);row.append(crop)
    while len(row)<4:row.append(np.zeros((340,440,3),np.uint8))
    sheets.append(np.hstack(row[:4]))
    np.savez_compressed(out/f'frame-{fi}.npz',keypoints=np.array([v[2] for v in candidates]),scores=np.array([v[0] for v in candidates]),tiles=np.array([v[1] for v in candidates]))
cap.release();cv2.imwrite(str(out/'comparison.jpg'),np.vstack(sheets))
(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
for r in results:
    if r['rank']==0:print(r)
