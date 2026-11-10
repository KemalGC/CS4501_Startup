"""Controlled time-support experiment; production settings are untouched."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from strokesense import kinematics,strokes,crew
from strokesense.pose import load_detections,crew_tracks,PoseResult
from synthetic import make_rower
smooth=kinematics.confidence_smooth

def build(kp,fps,wide=False):
    kinematics.confidence_smooth=(lambda values,confidence,rate,seconds=.15: smooth(values,confidence,rate,.3)) if wide else smooth
    try:return kinematics.build(kp,fps)
    finally:kinematics.confidence_smooth=smooth

synthetic=[]
for rate in [20,32,40]:
    clean,fps=make_rower(n_strokes=8,rate=rate,fps=30,noise=0)
    truth={'trunk':kinematics.tilt_from_vertical(np.zeros_like(clean[:,12,:2]),
                    (clean[:,6,:2]-clean[:,12,:2])*[1,-1]),
           'elbow':kinematics.angle_at(clean[:,6,:2],clean[:,8,:2],clean[:,10,:2]),
           'handle':(clean[:,10,0]-clean[:,12,0])/55}
    for noise in [0,1.5,3.]:
        for pattern in (['white'] if noise==0 else ['white','correlated']):
            for seed in (range(1) if noise==0 else range(5)):
                residual=np.random.default_rng(seed).normal(0,noise,clean[:,:,:2].shape)
                if pattern=='correlated':
                    for i in range(1,len(residual)):
                        residual[i]=.85*residual[i-1]+np.sqrt(1-.85**2)*residual[i]
                kp=clean.copy();kp[:,:,:2]+=residual
                for name,stride,wide in [('half_default',2,False),('full_default',1,False),('full_wide',1,True)]:
                    k=build(kp[::stride],fps/stride,wide);errors={}
                    for joint,true in truth.items():
                        pred=k.handle if joint=='handle' else k.angles[joint]
                        keep=np.isfinite(pred);keep[:5]=False;keep[-5:]=False
                        errors[joint]=float(np.sqrt(np.mean((pred[keep]-true[::stride][keep])**2)))
                    synthetic.append({'rate':rate,'noise_pixels':noise,'noise_model':pattern,'seed':seed,'variant':name,'rmse':errors})
print('SYNTHETIC',flush=True)
for pattern in ['white','correlated']:
    for noise in ([0,1.5,3.] if pattern=='white' else [1.5,3.]):
        for name in ['half_default','full_default','full_wide']:
            selected=[r for r in synthetic if r['noise_pixels']==noise and r['noise_model']==pattern and r['variant']==name]
            print(pattern,noise,name,{j:round(float(np.mean([r['rmse'][j] for r in selected])),4) for j in truth},flush=True)

path=ROOT/'results/full-rate-evaluation/IMG_9673--ebc59e58c20a888dfc7c/detections.npz'
dets,meta=load_detections(path);tracks,direction,seats=crew_tracks(dets,meta['fps'],expected_seats=8)
pose=PoseResult(meta['fps'],len(dets),meta['width'],meta['height'],tracks,start=meta['start'],stride=meta['stride'])
real=[]
for slot in sorted(tracks):
    kp=pose.dense(slot);row={'slot':slot}
    for name,wide in [('default',False),('wide',True)]:
        k=build(kp,meta['fps'],wide);found,_=strokes.analyse(k)
        row[name]=[{'catch':s.catch_t/meta['fps'],'finish':s.finish_t/meta['fps'],'next_catch':s.next_catch_t/meta['fps']} for s in found]
    real.append(row)
print('REAL CYCLES',sum(len(r['default']) for r in real),sum(len(r['wide']) for r in real),flush=True)
Path(__file__).with_name('filter_support_results.json').write_text(json.dumps({'scope':'Controlled synthetic localization RMSE plus real-data event diagnostics. Wider window experimental only.','synthetic':synthetic,'real':real},indent=2)+'\n')
