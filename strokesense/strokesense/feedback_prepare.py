"""Translate saved StrokeSense metrics into evidence-linked review aspects.

This module never turns reviewer ratings into technical model-accuracy scores.
Source files and manifests are private study assets, not repository fixtures.
"""
from __future__ import annotations
import hashlib
import json
import math
from .feedback import ASPECTS


def _number(value, digits=1):
    return f'{value:.{digits}f}' if type(value) in (int,float) and math.isfinite(value) else 'Unavailable'


def _rate_aspect(metrics, rowers):
    """The reviewable claim is the shared boat rate, not noisy track rates."""
    result = metrics.get('crew_cadence', {})
    rate = result.get('rate_spm')
    available = type(rate) in (int, float) and math.isfinite(rate) and rate > 0
    if not available:
        return {'status': 'unavailable',
                'summary': 'The software withheld a shared boat stroke rate because the observations did not establish a consistent crew rhythm.',
                'details': [{'label': 'Rate diagnostics',
                             'value': 'Raw per-track detections are diagnostic evidence, not separate rowing-rate claims.'}]}
    details = [{'label': 'Shared boat stroke rate', 'value': _number(rate)+' SPM'},
               {'label': 'Applies to', 'value': 'The whole selected boat; catch timing is assessed separately.'}]
    supporters = result.get('supporting_rowers')
    total = result.get('total_rowers', len(rowers))
    if type(supporters) is int and type(total) is int:
        details.append({'label': 'Supporting rower tracks', 'value': f'{supporters} of {total}'})
    span = result.get('support_duration_seconds')
    if type(span) in (int, float) and math.isfinite(span) and span > 0:
        details.append({'label': 'Overlapping rhythm evidence', 'value': _number(span)+' seconds'})
    rate_range = result.get('rate_range_spm')
    if isinstance(rate_range, (list, tuple)) and len(rate_range) == 2 and all(
            type(value) in (int, float) and math.isfinite(value) and value > 0 for value in rate_range):
        details.append({'label': 'Boat rhythm across supported windows',
                        'value': f'{rate_range[0]:.1f}–{rate_range[1]:.1f} SPM'})
    return {'status': 'available',
            'summary': f'Shared boat stroke rate: {_number(rate)} SPM. This summarizes the crew’s overall rhythm; early or late catches are timing differences.',
            'details': details}


def summarize_metrics(metrics, *, start=0., end=0., note='', method='YOLO11n pose estimation + deterministic StrokeSense analysis'):
    """Preserve raw findings and unavailable states; never infer absent values."""
    aspects={k:{'status':'unavailable','summary':'No model output was produced for this aspect.','details':[]} for k in ASPECTS}
    if metrics is None:
        aspects['tracking']={'status':'available','summary':'StrokeSense did not recover enough consistent rowing motion to release a technique report. Review whether that limitation matches the footage.','details':[]}
        aspects['evidence']={'status':'available','summary':'The original video and a clear limitation message are available. No technique score or supported crew rate was released.','details':[]}
        payload={'status':'unavailable','method':method,'window':{'start':float(start),'end':float(end)},'note':note,'aspects':aspects}
    else:
        rowers=metrics.get('rowers',[]);valid=[r for r in rowers if r.get('summary',{}).get('n_strokes',0)>0]
        counts=[int(r.get('summary',{}).get('n_strokes',0)) for r in rowers]
        aspects['tracking']={'status':'available','summary':f'The software produced {len(rowers)} rower tracks; {len(valid)} have at least one analyzed cycle. Seat names are automatic labels, not confirmed identities.','details':[{'label':'Reported rower tracks','value':str(len(rowers))},{'label':'Cycles across rower tracks','value':str(sum(counts))}]}
        aspects['rate']=_rate_aspect(metrics, rowers)
        positions=[{'label':f"Model seat {r.get('seat','?')}",'value':f"Catch {_number(r['summary'].get('trunk_catch'))}° / finish {_number(r['summary'].get('trunk_finish'))}°"} for r in valid]
        aspects['position']={'status':'available' if positions else 'unavailable','summary':'Projected 2D body angles from detected joints. Compare with the original viewpoint; these are not calibrated 3D measurements.','details':positions}
        issues=[]
        for r in valid:
            for finding in r['summary'].get('issues',[])[:3]:
                issues.append({'label':f"Model seat {r.get('seat','?')}",'value':finding.get('title','Unlabeled candidate finding')})
        ratios=[{'label':f"Model seat {r.get('seat','?')} · recovery : drive",'value':_number(r['summary'].get('ratio'))+' : 1'} for r in valid]
        aspects['sequencing']={'status':'available' if valid else 'unavailable','summary':'Candidate sequencing findings and cycle ratios. Check the movement, rather than rating whether the advice merely sounds plausible.','details':(issues or ratios)[:12]}
        timing=[{'label':f"Model seat {r.get('seat','?')}",'value':f"{_number(r['sync_ms'])} ms relative to model crew reference"} for r in rowers if type(r.get('sync_ms')) in (int,float)]
        aspects['timing']={'status':'available' if timing else 'unavailable','summary':'These offsets are model-derived, provisional catch timings—not confirmed early/late rowing. Small differences can be less than sampling uncertainty.','details':timing}
        aspects['evidence']={'status':'available','summary':'The detailed report contains source-linked snapshots, curves and candidate explanations. Check that they show the correct rower and support each claim.','details':[{'label':'Technique review status','value':'Not coach-validated'},{'label':'Evidence snapshot status','value':metrics.get('evidence',{}).get('status','Unspecified')}]}
        payload={'status':'provisional','method':method,'window':{'start':float(start),'end':float(end)},'note':note,'aspects':aspects}
    # Bind feedback to the exact metrics AND explanatory display, not a mutable filename.
    payload['version']=hashlib.sha256(json.dumps({'metrics':metrics,'display':payload},sort_keys=True,allow_nan=False).encode()).hexdigest()
    return payload
