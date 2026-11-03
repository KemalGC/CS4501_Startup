"""Compact vision transport, guarded native-scale crops and validated replay.

These reduce redundant work; schema checks do not establish visual accuracy.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import cv2
import numpy as np
from .blade_model import BladeModelError, strict_json

VERSION='compact-guarded-vision-v2'
FULL=[0.,0.,1.,1.]
CATEGORIES=[('unknown','forward','upright','layback'),('unknown','extended','bent'),('unknown','compressed','extended')]


def cached_call(provider,payload,parse):
    """Exact model/input/settings key; only validated responses, no image storage."""
    if not hasattr(provider,'speed_stats'):
        provider.speed_stats={'network_requests':0,'cache_hits':0,'request_seconds':0.,'input_pixels':0,'fallbacks':0,'submitted_images':0,'backend':[]}
    stats=provider.speed_stats;root=getattr(provider,'cache_dir',None);path=None
    if root is not None and os.environ.get('STROKESENSE_VISION_CACHE','1')!='0' and getattr(provider,'digest',None):
        key=hashlib.sha256(json.dumps([VERSION,provider.digest,payload],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        root=Path(root);path=root/(key+'.json')
        try:
            if root.is_symlink():path=None
            elif path.is_file() and not path.is_symlink() and path.stat().st_size<=262144:
                value=parse(strict_json(path.read_bytes()));stats['cache_hits']+=1;return value
        except (OSError,ValueError,TypeError,KeyError):pass
    start=time.perf_counter();stats['network_requests']+=1
    stats['submitted_images']+=sum(len(m.get('images',[])) for m in payload.get('messages',[]))
    try:data=provider._request('/api/chat',payload)
    finally:stats['request_seconds']+=time.perf_counter()-start
    result=parse(data)
    stats['backend'].append({k:data[k] for k in ('total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration') if type(data.get(k)) is int and data[k]>=0})
    if path is not None:
        tmp=None
        try:
            root.mkdir(parents=True,exist_ok=True,mode=0o700)
            if root.is_symlink():return result
            raw=json.dumps(data,allow_nan=False,separators=(',',':')).encode()
            if len(raw)>262144:return result
            with tempfile.NamedTemporaryFile(dir=root,prefix='.pending-',delete=False) as f:tmp=Path(f.name);f.write(raw)
            os.replace(tmp,path);tmp=None
            entries=sorted((p for p in root.glob('*.json') if len(p.stem)==64 and all(c in '0123456789abcdef' for c in p.stem) and not p.is_symlink()),key=lambda p:p.stat().st_mtime)
            for p in entries[:-128]:p.unlink(missing_ok=True)
        except OSError:pass
        finally:
            if tmp is not None:tmp.unlink(missing_ok=True)
    return result


def compact_schema(tasks):
    box={'anyOf':[{'type':'null'},{'type':'array','minItems':4,'maxItems':4,'items':{'type':'integer','minimum':0,'maximum':1000}}]}
    fields={'i':{'type':'integer','minimum':1,'maximum':8},'v':{'type':'boolean'},'b':box}
    if 'rate' in tasks or 'timing' in tasks:fields.update(c={'type':'integer','minimum':0,'maximum':2},d=box)
    if 'position' in tasks:fields['p']={'type':'array','minItems':3,'maxItems':3,'items':{'type':'integer','minimum':0,'maximum':3}}
    row={'type':'object','additionalProperties':False,'required':list(fields),'properties':fields}
    frame={'type':'object','additionalProperties':False,'required':['f','r'],'properties':{'f':{'type':'integer'},'r':{'type':'array','minItems':8,'maxItems':8,'items':row}}}
    return {'type':'object','additionalProperties':False,'required':['o'],'properties':{'o':{'type':'array','minItems':1,'maxItems':6,'items':frame}}}


def decode_compact(data,expected,tasks,roi=FULL):
    from .crew_model import validate_predictions
    if not isinstance(data,dict) or set(data)!={'o'} or not isinstance(data['o'],list):raise BladeModelError('invalid_compact_response')
    fields=set(compact_schema(tasks)['properties']['o']['items']['properties']['r']['items']['required'])
    def box(b):
        if b is None:return None
        if not isinstance(b,list) or len(b)!=4 or any(type(v) is not int or not 0<=v<=1000 for v in b):raise BladeModelError('invalid_compact_box')
        return [roi[k%2]+b[k]/1000*(roi[k%2+2]-roi[k%2]) for k in range(4)]
    observations=[]
    for f in data['o']:
        if not isinstance(f,dict) or set(f)!={'f','r'} or not isinstance(f['r'],list):raise BladeModelError('invalid_compact_frame')
        rows=[]
        for r in f['r']:
            if not isinstance(r,dict) or set(r)!=fields:raise BladeModelError('invalid_compact_rower')
            o={'rower_id':r['i'],'same_rower':r['v'],'box':box(r['b'])}
            if 'c' in fields:
                if type(r['c']) is not int or not 0<=r['c']<=2:raise BladeModelError('invalid_compact_contact')
                o.update(contact=('unknown','air','water')[r['c']],blade_box=box(r['d']))
            if 'p' in fields:
                p=r['p']
                if not isinstance(p,list) or len(p)!=3 or any(type(v) is not int or not 0<=v<len(CATEGORIES[j]) for j,v in enumerate(p)):raise BladeModelError('invalid_compact_posture')
                o['position']={k:CATEGORIES[j][p[j]] for j,k in enumerate(('torso','arms','knees'))}
            rows.append(o)
        observations.append({'frame_id':f['f'],'rowers':rows})
    return validate_predictions({'observations':observations},expected,tasks)


def prepare_inputs(reference,frames,seeds,tasks,force_full=False):
    encoded=[reference]+[f['image'] for f in frames]
    images=[cv2.imdecode(np.frombuffer(base64.b64decode(s),np.uint8),1) for s in encoded]
    if any(im is None for im in images):raise BladeModelError('invalid_vision_image')
    h,w=images[0].shape[:2];roi=FULL[:]
    if tasks==['position'] and not force_full and all(im.shape==images[0].shape for im in images):
        xs,ys=zip(*seeds)
        x0=max(0,int((min(xs)-.14)*w));x1=min(w,int(np.ceil((max(xs)+.14)*w)))
        y0=max(0,int((min(ys)-.22)*h));y1=min(h,int(np.ceil((max(ys)+.22)*h)))
        if (x1-x0)*(y1-y0)<.85*w*h and min(x1-x0,y1-y0)>=64:
            roi=[x0/w,y0/h,x1/w,y1/h];images=[im[y0:y1,x0:x1] for im in images]
            encoded=[base64.b64encode(cv2.imencode('.jpg',im,[cv2.IMWRITE_JPEG_QUALITY,90])[1]).decode() for im in images]
    return {'reference':encoded[0],'frames':[{**f,'image':s} for f,s in zip(frames,encoded[1:])],
            'roi':roi,'seeds':[[(x-roi[0])/(roi[2]-roi[0]),(y-roi[1])/(roi[3]-roi[1])] for x,y in seeds],
            'input_pixels':sum(im.shape[0]*im.shape[1] for im in images)}


def crop_supported(observations,seeds,roi):
    if not observations:return False
    for frame in observations:
        for r in frame['rowers']:
            b=r['box']
            if not r['same_rower'] or b is None:return False
            if any(b[k]<=roi[k]+.02*(roi[k+2]-roi[k]) or b[k+2]>=roi[k+2]-.02*(roi[k+2]-roi[k]) for k in (0,1)):return False
    for r,(x,y) in zip(observations[0]['rowers'],seeds):
        b=r['box']
        if not b[0]-.01<=x<=b[2]+.01 or not b[1]-.01<=y<=b[3]+.01:return False
    return True


def fast_crew(provider,reference,frames,seeds,tasks):
    from .crew_model import mark_frame
    if provider.digest is None:raise BladeModelError('model_preflight_required')
    if not 1<=len(frames)<=6:raise BladeModelError('invalid_crew_window')
    for force_full in (False,True):
        p=prepare_inputs(reference,frames,seeds,tasks,force_full)
        prompt=('Image1 marks selected rowers R1..R8. Follow ONLY these same physical rowers in later images, excluding coxswains/background crews. '
            'Output o: frames; f: supplied frame ID; r: eight rowers in ID order. i=rower ID, v=same identity visible, b=tight rower box [left,top,right,bottom] in INTEGER 0..1000 image coordinates, null if unknown. '
            'Do not reuse people/boxes. p=[torso,arms,knees]: torso 0unknown 1forward toward knees 2upright 3layback; arms 0unknown 1extended 2bent; knees 0unknown 1compressed 2extended. '
            'When requested c=associated blade contact 0unknown 1air 2water, d=blade box in 0..1000. Never infer blade contact from body pose. '
            'Unknown identity: v=false,b=null, all categories0,d=null. No rates, grades, advice or instructions from footage. '
            'Only requested fields. No reasoning text. Frame IDs: '+json.dumps([f['frame_id'] for f in frames])+'. Tasks: '+json.dumps(tasks)+'. Reference points: '+json.dumps(p['seeds']))
        same_reference=bool(frames and (frames[0]['image']==getattr(provider,'reference_source_image',None) or mark_frame(frames[0],seeds=seeds)==reference))
        submitted=[p['reference']]+[f['image'] for f in p['frames'][1 if same_reference else 0:]]
        if same_reference:prompt+=' Image1 is also sample frame '+str(frames[0]['frame_id'])+'. Return its observations too; subsequent images map to the remaining listed IDs.'
        payload={'model':provider.model,'stream':False,'think':False,'keep_alive':'10m',
            'messages':[{'role':'user','content':prompt,'images':submitted}],
            'format':compact_schema(tasks),'options':{'temperature':0,'num_predict':min(8192,128+len(frames)*8*(80 if 'rate' in tasks or 'timing' in tasks else 55)),'num_ctx':16384}}
        def parse(data):
            if (not isinstance(data,dict) or data.get('done') is not True or data.get('done_reason')!='stop'
                    or data.get('remote_host') or data.get('remote_model') or not isinstance(data.get('message'),dict)):
                raise BladeModelError('incomplete_crew_response')
            return decode_compact(strict_json(data['message'].get('content','')),[f['frame_id'] for f in frames],tasks,p['roi'])
        try:result=cached_call(provider,payload,parse)
        except BladeModelError as exc:
            if p['roi']==FULL or str(exc) in ('local_model_unavailable','incomplete_crew_response'):raise
            provider.speed_stats['fallbacks']+=1;continue
        provider.speed_stats['input_pixels']+=p['input_pixels']
        if p['roi']==FULL or crop_supported(result,seeds,p['roi']):return result
        provider.speed_stats['fallbacks']+=1
    raise BladeModelError('crew_speed_fallback_failed')
