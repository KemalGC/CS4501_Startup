"""Paired suppression from identical raw proposals and explicitly fixed crops."""
from detector_candidates import ROOT,detector
from pathlib import Path
import importlib.util,cv2,json,numpy as np
from strokesense.pose_merge import crop_edge_flags,merge_refined_detections
spec=importlib.util.spec_from_file_location('merge_v3',Path(__file__).with_name('baseline_pose_merge_v3.py'));old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
root=ROOT/'results/body-motion-evaluation';out=root/'crop-edge-comparison';out.mkdir(exist_ok=True)
manifest=json.loads((root/'detector-candidates/manifest.json').read_text());replay=json.loads((root/'torso-candidates/replay.json').read_text());labels=json.loads(Path(__file__).with_name('approximate_joint_labels.json').read_text())
z=np.load(ROOT/'results/model-tracking-evaluation/9674-boat1-candidate.npz');lookup={int(f):k for f,k in zip(z['0_frames'],z['0_kpts'])};z.close()
cases=[{'id':f'torso-{fi}','source':'IMG_9674','frame':fi*2,'tiles':replay['tiles']['cpu21'],'shoulder':lookup[fi][[5,6],:2].mean(0)} for fi in range(208,214)]
for case in labels['cases']:
    cases.append({'id':f'arm-{case["case"]}','source':case['source'],'frame':case['source_frame'],'tiles':manifest['clips'][case['source']]['tiles'],'shoulder':np.array(case['joints']['shoulder']),'truth':np.array([case['joints'][j] for j in ['shoulder','elbow','wrist']])})
model=detector(ROOT/'models/yolo11n-pose.onnx');results=[]
for case in cases:
    cap=cv2.VideoCapture(str(ROOT.parent.parent/'test-footage'/f"{case['source']}.MP4"));cap.set(cv2.CAP_PROP_POS_FRAMES,case['frame']);ok,frame=cap.read();cap.release()
    if not ok:raise RuntimeError('decode')
    H,W=frame.shape[:2];bs=[];ss=[];ks=[];edges=[]
    for x,y,x1,y1 in [(0,0,W,H)]+case['tiles']:
        b,s,k=model._infer(frame[y:y1,x:x1]);edges.append(crop_edge_flags(b,(x,y,x1,y1),W,H));b+=np.array([x,y,x,y]);k[:,:,:2]+=[x,y];bs.append(b);ss.append(s);ks.append(k)
    b,s,k,edge=map(np.concatenate,[bs,ss,ks,edges]);record={'case':case['id']};save={'raw_boxes':b,'raw_scores':s,'raw_keypoints':k,'crop_truncated':edge}
    for name,fn,kwargs in [('baseline',old.merge_refined_detections,{}),('candidate',merge_refined_detections,{'crop_truncated':edge})]:
        bb,score,kk=fn(b,s,k,**kwargs);idx=np.linalg.norm(kk[:,[5,6],:2].mean(1)-case['shoulder'],axis=1).argmin();pose=kk[idx]
        delta=(pose[6,:2]-pose[12,:2])*[1,-1];r={'detections':len(bb),'person_score':float(score[idx]),'hip':pose[12].tolist(),'trunk_angle':float(np.degrees(np.arctan2(delta[0],delta[1])))}
        if 'truth' in case:r['arm_errors']=np.linalg.norm(pose[[6,8,10],:2]-case['truth'],axis=1).tolist()
        record[name]=r;save[name]=pose
    results.append(record);np.savez_compressed(out/f"{case['id']}.npz",**save)
    print(case['id'],round(record['baseline']['trunk_angle'],1),round(record['candidate']['trunk_angle'],1),record['baseline']['detections'],record['candidate']['detections'],flush=True)
(out/'results.json').write_text(json.dumps({'scope':'Identical raw proposals, fixed crop grids. Six torso failure frames plus six approximate assistant arm cases. Selected development diagnostic, not independent ground truth.','cases':results},indent=2)+'\n')
