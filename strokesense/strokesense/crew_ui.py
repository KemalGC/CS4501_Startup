"""Selectable tasks for eight explicitly confirmed same-boat rowers."""
from __future__ import annotations
import base64
import hmac
import html
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import parse_qs,urlsplit
from . import web
from .blade_video import reference_frame
from .crew_model import validate_options
from .registry import list_clips,_stream_sha256


def configured_model():
    return os.environ.get('STROKESENSE_CREW_MODEL',os.environ.get('STROKESENSE_BLADE_MODEL','')).strip()


def add_crew_routes(server,jobs,registry):
    base=server.RequestHandlerClass
    def source_for(cid):
        if not re.fullmatch('[a-f0-9]{64}',cid):raise ValueError('invalid_clip')
        record=next((c for c in list_clips(registry,show_paths=True) if c['clip_id']==cid),None)
        if record is None:raise LookupError('missing_clip')
        if record['permission']!='granted':raise PermissionError('permission_required')
        p=Path(record['source_path'])
        if p.stat().st_size>web._MAX_VIDEO_BYTES or _stream_sha256(p)!=record['sha256']:raise ValueError('source_changed')
        return p
    class CrewHandler(base):
        def crew_problem(self,status):
            text={403:'Permission or request validation failed.',404:'Saved clip unavailable.',
                422:'Choose eight distinct rowers, at least one analysis, and confirm they belong to one boat.',
                409:'Recording changed or reference frame could not be decoded.',
                503:'No local crew vision model is configured, or its storage is unavailable. Start with --crew-model MODEL.'}[status]
            self._send(status,web._document('Crew review unavailable','<p role="alert">'+text+'</p><a href="/library">Back to library</a>'))
        def do_GET(self):
            route=urlsplit(self.path)
            if route.path not in ('/crew','/crew.js'):return super().do_GET()
            if not self._trusted_request():self.crew_problem(403);return
            if route.path=='/crew.js':
                if route.query:self.crew_problem(422);return
                self._send(200,CREW_JS.encode(),mime='application/javascript; charset=utf-8');return
            try:
                if len(route.query)>120:raise ValueError('query_too_large')
                q=parse_qs(route.query,strict_parsing=True,keep_blank_values=True,max_num_fields=2)
                if set(q)-{'clip','seconds'} or 'clip' not in q or any(len(v)!=1 for v in q.values()):raise ValueError('invalid_query')
                cid=q['clip'][0];source=source_for(cid);when=float(q.get('seconds',['0'])[0])
                if not math.isfinite(when) or not 0<=when<=600:raise ValueError('invalid_time')
                image,actual=reference_frame(source,when);source_for(cid)
                body=page(cid,actual,image,server.csrf_token,configured_model())
                self._send(200,web._document('Choose crew analyses',body),csp=web._PAGE_CSP+"; img-src data:; script-src 'self'")
            except PermissionError:self.crew_problem(403)
            except LookupError:self.crew_problem(404)
            except (ValueError,OSError):self.crew_problem(409)
            except Exception:self.crew_problem(503)
        def do_POST(self):
            route=urlsplit(self.path)
            if route.path!='/crew':return super().do_POST()
            if not self._trusted_request():self.crew_problem(403);return
            try:
                lengths=self.headers.get_all('Content-Length') or []
                if (route.query or len(lengths)!=1 or not re.fullmatch(r'[0-9]{1,4}',lengths[0])
                        or self.headers.get_all('Transfer-Encoding') or self.headers.get_content_type()!='application/x-www-form-urlencoded'):
                    raise ValueError('invalid_request')
                length=int(lengths[0])
                if not 0<length<=4096:raise ValueError('invalid_size')
                self.connection.settimeout(5);raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete_body')
                f=parse_qs(raw.decode(),strict_parsing=True,keep_blank_values=True,max_num_fields=8)
                if (set(f)!={'clip','csrf','seconds','seeds','analysis','confirm'}
                        or any(len(v)!=1 for k,v in f.items() if k!='analysis')):raise ValueError('invalid_fields')
                if not hmac.compare_digest(f['csrf'][0].encode(),server.csrf_token.encode()):self.crew_problem(403);return
                chosen=validate_options({'version':4,'kind':'crew_model','reference_seconds':float(f['seconds'][0]),
                   'seeds':json.loads(f['seeds'][0]),'analyses':f['analysis'],'confirmed_same_boat':f['confirm']==['yes']})
                source=source_for(f['clip'][0]);reference_frame(source,chosen['reference_seconds'])
                if not configured_model():self.crew_problem(503);return
                job=jobs.submit(f['clip'][0],selection=chosen)
                self._send(303,b'',location='/jobs/'+job['job_id'])
            except PermissionError:self.crew_problem(403)
            except LookupError:self.crew_problem(404)
            except (ValueError,TypeError,OSError,TimeoutError):self.crew_problem(422)
            except Exception:self.crew_problem(503)
    server.RequestHandlerClass=CrewHandler
    return server


def page(cid,when,image,csrf,model):
    return ('<p>Choose what to analyze, then mark <strong>eight rowers from the same boat</strong>. '
      'One shared model request handles all eight; unselected tasks are omitted. This is experimental model review, not verified coaching.</p>'
      f'<form method="get" action="/crew"><input type="hidden" name="clip" value="{cid}">'
      f'<label>Reference time (seconds)<input type="number" name="seconds" min="0" max="600" step="0.1" value="{when:g}"></label>'
      '<button>Show reference frame</button></form>'
      '<form method="post" action="/crew" id="crew-form">'
      f'<input type="hidden" name="csrf" value="{html.escape(csrf,quote=True)}"><input type="hidden" name="clip" value="{cid}">'
      f'<input type="hidden" name="seconds" value="{when:.8f}"><input type="hidden" name="seeds" value="[]">'
      '<fieldset><legend>1. Select analyses</legend>'
      '<label><input type="checkbox" name="analysis" value="position" checked> Body positions — torso, arms and knees at three sampled times</label>'
      '<label><input type="checkbox" name="analysis" value="rate"> Stroke rate — two blade entries per rower, where visible</label>'
      '<label><input type="checkbox" name="analysis" value="timing"> Crew catch timing — supported blade-entry differences</label>'
      '<p>Position-only uses one short batch. Rate/timing need additional frames and clear blade-to-rower association; hidden blades stay unavailable.</p></fieldset>'
      '<fieldset><legend>2. Confirm your eight</legend><p>Click the center of each rower’s torso, in a consistent order. Exclude the coxswain and other boats. '
      'These are selection IDs, not automatic bow/stroke-seat labels. Use the coordinate fields as a keyboard alternative.</p>'
      '<canvas id="crew-canvas" tabindex="0" style="width:100%;height:auto;border:2px solid #087f70" aria-label="Mark eight same-boat rowers"></canvas>'
      f'<img hidden id="crew-image" alt="Source reference frame" src="data:image/jpeg;base64,{base64.b64encode(image).decode()}">'
      '<p><button type="button" id="crew-undo">Undo last rower</button> <button type="button" id="crew-clear">Clear selection</button></p>'
      '<div id="crew-coordinates"></div><p id="crew-count" role="status" aria-live="polite">0 of 8 selected</p>'
      '<label><input type="checkbox" name="confirm" value="yes" required> These eight rowers belong to the same boat.</label></fieldset>'
      f'<button type="submit" id="crew-submit" data-configured="{str(bool(model)).lower()}" disabled>Analyze selected tasks</button></form>'
      + (f'<p>Local model: <code>{html.escape(model)}</code>. Its accuracy on your recording is not yet established.</p>' if model else
         '<p role="alert">Configure a local vision model with --crew-model MODEL. The app never downloads one or falls back to heuristic grades.</p>')
      +'<p><a href="/library">Back to library</a></p><script src="/crew.js" defer></script>')


CREW_JS=r"""'use strict';
(()=>{
 const form=document.getElementById('crew-form'),canvas=document.getElementById('crew-canvas'),image=document.getElementById('crew-image');
 const ctx=canvas.getContext('2d'),submit=document.getElementById('crew-submit');let points=[];
 const coordinates=document.getElementById('crew-coordinates');
 for(let i=0;i<8;i++){
  const wrap=document.createElement('div');wrap.style.display='flex';wrap.style.gap='12px';wrap.style.flexWrap='wrap';
  ['X','Y'].forEach((axis,j)=>{const label=document.createElement('label'),input=document.createElement('input');
   label.textContent='R'+(i+1)+' '+axis+' (0–1) ';input.type='number';input.min='.001';input.max='.999';input.step='.001';input.style.width='6em';
   input.dataset.row=i;input.dataset.axis=j;input.setAttribute('aria-label','R'+(i+1)+' '+axis);label.append(input);wrap.append(label);
   input.addEventListener('input',()=>{const fields=coordinates.querySelectorAll('input');points=[];
    for(let k=0;k<8;k++){const x=Number(fields[2*k].value),y=Number(fields[2*k+1].value);if(x>0&&x<1&&y>0&&y<1)points.push([x,y]);else break;}sync(false);});});coordinates.append(wrap);
 }
 function draw(){if(!image.complete||!image.naturalWidth)return;canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;ctx.drawImage(image,0,0);
  points.forEach((p,i)=>{const x=p[0]*canvas.width,y=p[1]*canvas.height;ctx.beginPath();ctx.strokeStyle='#b32d1a';ctx.lineWidth=3;ctx.arc(x,y,8,0,Math.PI*2);ctx.stroke();ctx.font='bold 18px sans-serif';ctx.fillStyle='#b32d1a';ctx.fillText('R'+(i+1),x+10,y-8);});}
 function sync(update=true){form.elements.namedItem('seeds').value=JSON.stringify(points);form.elements.namedItem('confirm').checked=false;
  document.getElementById('crew-count').textContent=points.length+' of 8 selected';
  submit.disabled=submit.dataset.configured!=='true'||points.length!==8||!form.querySelector('[name=analysis]:checked');
  if(update){coordinates.querySelectorAll('input').forEach(e=>e.value=points[Number(e.dataset.row)]?.[Number(e.dataset.axis)]?.toFixed(3)||'');}draw();}
 canvas.addEventListener('click',e=>{if(points.length>=8)return;const r=canvas.getBoundingClientRect();points.push([Math.min(.999,Math.max(.001,(e.clientX-r.left)/r.width)),Math.min(.999,Math.max(.001,(e.clientY-r.top)/r.height))]);sync();});
 document.getElementById('crew-undo').addEventListener('click',()=>{points.pop();sync();});document.getElementById('crew-clear').addEventListener('click',()=>{points=[];sync();});
 form.querySelectorAll('[name=analysis]').forEach(e=>e.addEventListener('change',()=>sync(false)));
 image.addEventListener('load',draw);draw();
})();
"""
