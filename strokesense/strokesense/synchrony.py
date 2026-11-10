"""Crew catch association with independent identity support and one-use events."""
from collections import Counter
import math
import numpy as np

VERSION = 'one-use-crew-events-v1'


def finite(value):
    return isinstance(value,(int,float,np.integer,np.floating)) and not isinstance(value,(bool,np.bool_)) and math.isfinite(value)


def match_events(rowers, fps):
    """Return supported event groups, never manufacturing missing catches.

    Each physical identity contributes at most one event per group and each
    detected catch can be used only once. Multiple nearby candidates from one
    identity are ambiguous and do not vote. A strict crew majority is required.
    """
    if not finite(fps) or fps <= 0:
        raise ValueError('invalid synchrony frame rate')
    ids=Counter(r.tid for r in rowers);seats=Counter(r.seat for r in rowers)
    minimum=max(2,len(rowers)//2+1)
    events=[];periods=[]
    for rower in rowers:
        if ids[rower.tid]!=1 or seats[rower.seat]!=1:
            continue
        row_fps=getattr(getattr(rower,'k',None),'fps',fps)
        if not finite(row_fps) or not math.isclose(row_fps,fps,rel_tol=1e-8):
            continue
        unique={};duration=[]
        for stroke in rower.strokes:
            a,b=getattr(stroke,'catch_t',None),getattr(stroke,'next_catch_t',None)
            if not finite(a) or not finite(b) or a<0 or not 1.2 <= (b-a)/fps <= 5.:
                continue
            duration.append(b-a)
            for t in (a,b):unique.setdefault(round(float(t),8),float(t))
        if duration:
            # Equal identity weights: an over-detecting rower cannot dominate.
            periods.append(float(np.median(duration)))
            events.extend({'rower':rower.tid,'seat':rower.seat,'frame':t} for t in unique.values())
    if len(periods)<minimum:
        return []
    period=float(np.median(periods));radius=.175*period
    events.sort(key=lambda e:(e['frame'],str(e['rower'])))
    times=np.array([e['frame'] for e in events]);candidates={}
    for seed in times:
        centre=seed;chosen=[]
        for _ in range(3):
            near=np.flatnonzero(np.abs(times-centre)<=radius)
            counts=Counter(events[i]['rower'] for i in near)
            chosen=[int(i) for i in near if counts[events[i]['rower']]==1]
            if len(chosen)<minimum:
                chosen=[];break
            centre=float(np.median(times[chosen]))
        if chosen:
            candidates[tuple(chosen)]=centre
    ranked=sorted(candidates.items(),key=lambda item:(-len(item[0]),
           float(np.median(np.abs(times[list(item[0])]-item[1]))),item[1]))
    used=set();groups=[]
    for indices,centre in ranked:
        if used.intersection(indices):
            continue
        used.update(indices)
        groups.append({'frame':centre,'observations':[events[i] for i in indices]})
    return sorted(groups,key=lambda g:g['frame'])
