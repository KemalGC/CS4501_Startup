"""Local person-crop experiment; no production detector changes."""
from detector_candidates import ROOT, detector
import cv2,json,numpy as np
from pathlib import Path

root=ROOT/'results/body-motion-evaluation/detector-candidates'
output=ROOT/'results/body-motion-evaluation/crop-refinement';output.mkdir(parents=True,exist_ok=True)
labels=json.loads(Path(__file__).with_name('approximate_joint_labels.json').read_text())
model=detector(ROOT/'models/yolo11n-pose.onnx');results=[];sheets=[]
for case in labels['cases']:
    cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage'/f"{case['source']}.MP4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES,case['source_frame']);ok,frame=cap.read();cap.release()
    if not ok:raise ValueError('decode failed')
    a,b,c,d=case['crop_xyxy'];centre=np.array([(a+c)/2,(b+d)/2])
    with np.load(root/f"{case['source']}-{case['source_frame']}-n.npz") as z:
        j=np.linalg.norm((z['boxes'][:,:2]+z['boxes'][:,2:])/2-centre,axis=1).argmin()
        box=z['boxes'][j].copy();base=z['keypoints'][j].copy()
    variants={'base':base};bounds={}
    for pad in [.35,.65,1.]:
        size=box[2:]-box[:2];margin=np.max(size)*pad
        x,y,x1,y1=np.rint(box+[-margin,-margin,margin,margin]).astype(int)
        x,y=max(0,x),max(0,y);x1,y1=min(frame.shape[1],x1),min(frame.shape[0],y1)
        bb,score,kk=model(frame[y:y1,x:x1]);bb+=np.array([x,y,x,y]);kk[:,:,:2]+=[x,y]
        if not len(bb):continue
        target=(box[:2]+box[2:])/2
        selected=np.linalg.norm((bb[:,:2]+bb[:,2:])/2-target,axis=1).argmin()
        variants[str(pad)]=kk[selected];bounds[str(pad)]=[x,y,x1,y1]
    np.savez_compressed(output/f"case-{case['case']}.npz",**variants)
    row=[];truth=np.array([case['joints'][name] for name in ['shoulder','elbow','wrist']])
    for name,k in variants.items():
        errors=np.linalg.norm(k[[6,8,10],:2]-truth,axis=1)
        results.append({'case':case['case'],'variant':name,'errors':errors.tolist(),'confidence':k[[6,8,10],2].tolist()})
        im=frame.copy()
        for u,v in [(6,8),(8,10),(6,12),(12,14)]:cv2.line(im,tuple(np.rint(k[u,:2]).astype(int)),tuple(np.rint(k[v,:2]).astype(int)),(0,255,0),1)
        for j,color in [(6,(255,0,0)),(8,(0,255,255)),(10,(0,0,255)),(12,(0,255,0)),(14,(255,255,0))]:cv2.circle(im,tuple(np.rint(k[j,:2]).astype(int)),2,color,-1)
        crop=cv2.resize(im[b:d,a:c],(320,240));cv2.putText(crop,f"Case {case['case']} / {name}",(5,20),0,.6,(255,255,255),2);row.append(crop)
    if len(row)==4:sheets.append(np.hstack(row))
cv2.imwrite(str(output/'comparison.jpg'),np.vstack(sheets))
(output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
for name in ['base','.35','.65','1.0','0.35','0.65']:
    r=[x['errors'] for x in results if x['variant']==name]
    if r:print(name,np.round(np.mean(r,axis=0),2),round(np.mean(r),2))
