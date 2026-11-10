"""Known-motion body benchmark; simulated corruption is not video ground truth."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from strokesense import kinematics
from synthetic import make_rower
spec=importlib.util.spec_from_file_location('body_motion_baseline',Path(__file__).with_name('baseline_kinematics.py'))
baseline=importlib.util.module_from_spec(spec);sys.modules[spec.name]=baseline;spec.loader.exec_module(baseline)


def truth(kp):
    sh,el,wr,hip,knee=[kp[:,i,:2] for i in [6,8,10,12,14]]
    d=sh-hip
    return {'trunk':np.degrees(np.arctan2(d[:,0],-d[:,1])),
            'elbow':kinematics.angle_at(sh,el,wr),
            'handle':(wr[:,0]-hip[:,0])/55.,
            'thigh':np.degrees(np.arctan2(hip[:,1]-knee[:,1],np.abs(knee[:,0]-hip[:,0])))}


def main():
    result={'scope':'Synthetic known-motion benchmark; no independent real-video accuracy claim.',
            'assumptions':'Low-confidence estimates have more simulated noise; isolated high-confidence joint jumps and shared camera translation are injected.',
            'cases':[]}
    for fps in [15,30]:
        for rate in [20,32,40]:
            clean,_=make_rower(n_strokes=6,rate=rate,fps=fps,noise=0)
            target=truth(clean)
            for condition in ['clean','variable_noise','joint_spikes','camera_and_noise']:
                kp=clean.copy();rng=np.random.default_rng(20261110+fps+rate)
                if condition in ['variable_noise','camera_and_noise']:
                    for j in range(5,17):
                        low=rng.random(len(kp))<.2
                        kp[:,j,2]=np.where(low,.4,.95) if j%2==0 else .55
                        sigma=np.where(low,7.,.8)
                        kp[:,j,:2]+=rng.normal(size=(len(kp),2))*sigma[:,None]
                if condition=='joint_spikes':
                    for offset,j in [(40,10),(60,6),(80,12)]:
                        kp[offset::97,j,:2]+=[45,-30]
                if condition=='camera_and_noise':
                    t=np.arange(len(kp));kp[:,:,:2]+=np.c_[70*np.sin(t*.19)+t*.8,25*np.cos(t*.29)][:,None]
                entry={'fps':fps,'rate':rate,'condition':condition}
                for name,module in [('baseline',baseline),('candidate',kinematics)]:
                    k=module.build(kp,fps)
                    metrics={}
                    for signal,expected in target.items():
                        actual=k.handle if signal=='handle' else k.angles[signal]
                        mask=np.isfinite(actual);mask[:5]=False;mask[-5:]=False
                        metrics[signal+'_rmse']=float(np.sqrt(np.mean((actual[mask]-expected[mask])**2)))
                    metrics['rejected']=sum(int(v.sum()) for v in getattr(k,'rejected',{}).values())
                    metrics['visible_fraction']=float(k.visible.mean())
                    entry[name]=metrics
                result['cases'].append(entry)
    output=ROOT/'results/body-motion-evaluation';output.mkdir(parents=True,exist_ok=True)
    (output/'synthetic-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    for condition in ['clean','variable_noise','joint_spikes','camera_and_noise']:
        entries=[e for e in result['cases'] if e['condition']==condition]
        print(condition)
        for metric in ['trunk_rmse','elbow_rmse','handle_rmse','thigh_rmse']:
            print(metric,*(round(np.mean([e[name][metric] for e in entries]),4) for name in ['baseline','candidate']))

if __name__=='__main__':main()
