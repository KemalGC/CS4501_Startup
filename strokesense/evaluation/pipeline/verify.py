"""Check saved measurement invariants after real-video inference and rendering."""
import hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from strokesense import evidence
path=Path(sys.argv[1]);data=json.loads(path.read_text());fps=data['evidence']['fps']
assert evidence.verify_evidence_snapshot(data['evidence'])
assert evidence.validate_reference_graph(data['evidence'])
counts=[];cycles=0
for r in data['rowers']:
    for s in r['strokes']:
        c,f,n=(s[name] for name in ('catch_t','finish_t','next_catch_t'))
        assert c<f<n
        for name,t in [('catch',c),('finish',f),('next_catch',n)]:assert abs(s[name]-t)<=.5
        assert math.isclose(s['drive_s'],(f-c)/fps,abs_tol=1e-10)
        assert math.isclose(s['recovery_s'],(n-f)/fps,abs_tol=1e-10)
        assert math.isclose(60/s['rate'],s['drive_s']+s['recovery_s'],abs_tol=1e-10)
        assert s['observed_frames']+s['gap_frames']==s['next_catch']-s['catch']+1
        cycles+=1
    for values in r['joint_observation_counts'].values():
        assert all(type(v) is int and v>=0 for v in values.values())
        counts.append(sum(values.values()))
assert len(set(counts))==1
seen=set();groups=data['sync']['matched_events']
for g in groups:
    obs=g['observations'];assert len(obs)>=len(data['rowers'])//2+1
    assert len({o['rower'] for o in obs})==len(obs)
    for o in obs:
        key=(o['rower'],o['frame']);assert key not in seen;seen.add(key)
summary={'scope':'Fresh inference, tracking, measurements, annotated-video rendering and report serialization. Numerical/provenance invariants; not independent real-video accuracy.',
 'metrics_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
 'rowers':len(data['rowers']),'cycles':cycles,'frames_per_joint':counts[0],
 'fps':fps,'supported_crew_events':len(groups),'crew_cadence':data['crew_cadence']['rate_spm'],
 'measurement_policy':data['measurement_policy'],'checks':'passed'}
print(json.dumps(summary,indent=2))
