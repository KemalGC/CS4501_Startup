"""Private bounded multi-frame review routes for the existing library server."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hmac
import html
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from . import web
from .multiframe import scan_clip
from .registry import list_clips, _stream_sha256
from .selection import validate_selection

_ID = re.compile(r'[0-9a-f]{64}\Z')


def review_html(cid, csrf):
    return (
        '<h2>Review later frames and choose one crew</h2>'
        '<p>Scan up to five frames across the first 20 seconds. Choose a clearer frame, '
        'inspect a suggested boat group, then confirm eight rowers. Nothing is preselected.</p>'
        '<p><strong>Boat regions are suggestions from rower alignment, not verified hull detection.</strong> '
        'Exclude the coxswain and other crews. Never mix identities across separate preview frames.</p>'
        '<p id="review-status" role="status" aria-live="polite">Scanning local frames…</p>'
        '<nav id="review-frames" aria-label="Reference frames"></nav>'
        '<nav id="review-boats" aria-label="Suggested boat groups"></nav>'
        '<canvas id="review-canvas" style="width:100%;height:auto;border:2px solid #087f70" '
        'aria-label="Detected people and suggested boat region"></canvas>'
        '<form method="post" action="/review/confirm" id="review-form">'
        f'<input type="hidden" name="csrf" value="{html.escape(csrf,quote=True)}">'
        f'<input type="hidden" name="clip" value="{cid}">'
        '<input type="hidden" name="review"><input type="hidden" name="frame" value="0">'
        '<input type="hidden" name="people"><fieldset id="review-people"><legend>Detected people</legend></fieldset>'
        '<p id="review-count" role="status">0 of 8 selected</p>'
        '<label><input type="checkbox" name="same_boat" value="yes" required> '
        'I confirm these eight rowers belong to the same boat, excluding the coxswain.</label>'
        '<button type="submit" disabled>Analyze confirmed crew</button></form>'
        '<p>Tracking follows the confirmed identities forward and backward from this frame. '
        'Missing or ambiguous observations remain gaps, not replacement rowers or invented measurements.</p>'
        f'<p><a href="/select?clip={cid}">Manual first-frame selection</a> · '
        '<a href="/library">Manage library</a></p><script src="/review.js" defer></script>'
    )


def add_review(server, jobs, registry, *, scan_fn=scan_clip):
    """Attach small additive routes; keep existing upload/selection/report routes."""
    base=server.RequestHandlerClass
    registry=Path(registry).expanduser().resolve()
    cache={}; lock=threading.Lock(); executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='clip-review')
    original_close=server.server_close
    def close():
        executor.shutdown(wait=True,cancel_futures=True)
        original_close()
    server.server_close=close

    def clip_for(cid):
        if not _ID.fullmatch(cid): raise ValueError('invalid_clip')
        clip=next((c for c in list_clips(registry,show_paths=True) if c['clip_id']==cid),None)
        if clip is None: raise LookupError('missing_clip')
        if clip['permission']!='granted': raise PermissionError('permission_required')
        source=Path(clip['source_path'])
        if source.stat().st_size>web._MAX_VIDEO_BYTES or _stream_sha256(source)!=clip['sha256']:
            raise ValueError('source_changed')
        return source

    def scan(cid):
        source=clip_for(cid);result=scan_fn(source);clip_for(cid)
        return result

    class ReviewHandler(base):
        def _send(self,code,data,**kwargs):
            # Redirect only the library launcher's import selection, not reports.
            location=kwargs.get('location')
            if isinstance(location,str) and location.startswith('/select?clip='):
                kwargs['location']=location.replace('/select?clip=','/review?clip=',1)
            if urlsplit(self.path).path == '/library' and kwargs.get('csp')!=web._REPORT_CSP:
                data=data.replace(b'href="/select?clip=',b'href="/review?clip=')
            return super()._send(code,data,**kwargs)

        def _review_error(self,code):
            messages={403:'Permission or request validation failed. No analysis was started.',
                      404:'This saved clip or review no longer exists.',
                      409:'The recording or review changed. Reload the review before confirming.',
                      422:'Choose exactly eight distinct detected people in one frame and confirm the same boat.',
                      503:'Another preview is running or local preview storage is unavailable. Try again after it finishes.'}
            self._send(code,web._document('Review unavailable',
                '<p role="alert">'+messages.get(code,messages[422])+'</p><p><a href="/library">Back to library</a></p>'))

        def do_GET(self):
            parsed=urlsplit(self.path)
            if parsed.path not in ('/review','/review/status','/review.js'): return super().do_GET()
            if not self._trusted_request(): self._review_error(403);return
            if parsed.path=='/review.js':
                if parsed.query: self._review_error(422);return
                self._send(200,REVIEW_JS.encode(),mime='application/javascript; charset=utf-8');return
            try:
                if len(parsed.query)>80: raise ValueError('invalid_query')
                params=parse_qs(parsed.query,strict_parsing=True,max_num_fields=1)
                if set(params)!={'clip'} or len(params['clip'])!=1: raise ValueError('invalid_query')
                cid=params['clip'][0];clip_for(cid)
                with lock:
                    entry=cache.get(cid)
                    if entry is None:
                        if parsed.path=='/review/status': raise LookupError('missing_review')
                        if any(not v['future'].done() for v in cache.values()):
                            self._review_error(503);return
                        if len(cache)>=4: cache.pop(next(iter(cache)))
                        entry={'review':uuid4().hex,'future':executor.submit(scan,cid)};cache[cid]=entry
                if parsed.path=='/review':
                    self._send(200,web._document('Review your boat',review_html(cid,server.csrf_token)),
                               csp=web._PAGE_CSP+"; img-src data:; script-src 'self'");return
                if not entry['future'].done(): payload={'state':'scanning'}
                else:
                    payload=entry['future'].result()
                    payload={**payload,'review':entry['review']}
                self._send(200,json.dumps(payload,allow_nan=False).encode(),mime='application/json; charset=utf-8')
            except PermissionError: self._review_error(403)
            except LookupError: self._review_error(404)
            except (ValueError,OSError): self._review_error(409)
            except Exception: self._review_error(503)

        def do_POST(self):
            parsed=urlsplit(self.path)
            if parsed.path!='/review/confirm': return super().do_POST()
            if not self._trusted_request(): self._review_error(403);return
            try:
                lengths=self.headers.get_all('Content-Length') or []
                if (parsed.query or len(lengths)!=1 or not re.fullmatch('[0-9]{1,4}',lengths[0])
                        or self.headers.get_all('Transfer-Encoding')
                        or self.headers.get_content_type()!='application/x-www-form-urlencoded'):
                    raise ValueError('invalid_form')
                size=int(lengths[0])
                if not 0<size<=4096: raise ValueError('invalid_size')
                self.connection.settimeout(5);raw=self.rfile.read(size)
                if len(raw)!=size: raise ValueError('incomplete_form')
                f=parse_qs(raw.decode(),strict_parsing=True,keep_blank_values=True,max_num_fields=6)
                if set(f)!={'csrf','clip','review','frame','people','same_boat'} or any(len(v)!=1 for v in f.values()):
                    raise ValueError('invalid_form')
                f={k:v[0] for k,v in f.items()}
                if not hmac.compare_digest(f['csrf'].encode(),server.csrf_token.encode()):
                    self._review_error(403);return
                cid=f['clip'];clip_for(cid)
                with lock: entry=cache.get(cid)
                if entry is None or not hmac.compare_digest(f['review'],entry['review']) or not entry['future'].done():
                    self._review_error(409);return
                data=entry['future'].result()
                if data['state']!='ready' or not re.fullmatch('[0-4]',f['frame']): raise ValueError('invalid_reference')
                reference=data['frames'][int(f['frame'])]
                if not re.fullmatch(r'[0-9]{1,2}(,[0-9]{1,2}){7}',f['people']): raise ValueError('invalid_people')
                ids=[int(i) for i in f['people'].split(',')]
                if len(set(ids))!=8 or f['same_boat']!='yes': raise ValueError('invalid_selection')
                points=[reference['candidates'][i]['seed'] for i in ids]
                selected=validate_selection({'version':2,'reference_seconds':reference['seconds'],
                    'roi':[0,0,1,1],'seeds':points,'confirmed_same_boat':True})
                job=jobs.submit(cid,selection=selected)
                self._send(303,b'',location='/jobs/'+job['job_id'])
            except PermissionError: self._review_error(403)
            except LookupError: self._review_error(422)
            except (ValueError,TypeError,OSError,TimeoutError): self._review_error(422)
            except Exception: self._review_error(503)
    server.RequestHandlerClass=ReviewHandler
    return server


REVIEW_JS=r"""'use strict';
(() => {
 const form=document.getElementById('review-form'), canvas=document.getElementById('review-canvas');
 const ctx=canvas.getContext('2d'), status=document.getElementById('review-status'), image=new Image();
 let data=null, frame=0, chosen=[], boat=null;
 const field=n=>form.elements.namedItem(n);
 function allowed(i){return boat===null || data.frames[frame].boats[boat].members.includes(i);}
 function draw(){
  if(!image.complete || !image.naturalWidth)return;
  canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;ctx.drawImage(image,0,0);
  if(boat!==null){const b=data.frames[frame].boats[boat].box;ctx.strokeStyle='#ad5b00';ctx.lineWidth=4;ctx.strokeRect(b[0]*canvas.width,b[1]*canvas.height,(b[2]-b[0])*canvas.width,(b[3]-b[1])*canvas.height);}
  data.frames[frame].candidates.forEach((c,i)=>{
   if(!allowed(i))return;const b=c.box;ctx.strokeStyle=chosen.includes(i)?'#087454':'#245ac7';ctx.lineWidth=chosen.includes(i)?4:2;
   ctx.strokeRect(b[0]*canvas.width,b[1]*canvas.height,(b[2]-b[0])*canvas.width,(b[3]-b[1])*canvas.height);
   ctx.fillStyle=ctx.strokeStyle;ctx.fillRect(b[0]*canvas.width,b[1]*canvas.height,55,22);ctx.fillStyle='white';ctx.font='bold 14px sans-serif';ctx.fillText('P'+c.id,b[0]*canvas.width+3,b[1]*canvas.height+16);
  });
 }
 function sync(){
  field('people').value=chosen.join(',');field('same_boat').checked=false;
  document.getElementById('review-count').textContent=chosen.length+' of 8 selected';
  form.querySelector('button[type=submit]').disabled=chosen.length!==8;
  form.querySelectorAll('.review-person').forEach(e=>e.checked=chosen.includes(Number(e.dataset.index)));draw();
 }
 function toggle(i){
  if(!allowed(i)||!data.frames[frame].candidates[i].seed)return;
  if(chosen.includes(i))chosen=chosen.filter(x=>x!==i);
  else if(chosen.length<8)chosen.push(i);
  else status.textContent='Eight already selected. Deselect someone first.';
  sync();
 }
 function people(){
  const list=document.getElementById('review-people');list.replaceChildren();
  const legend=document.createElement('legend');legend.textContent='Choose eight rowers from this boat';list.append(legend);
  data.frames[frame].candidates.forEach((c,i)=>{
   if(!allowed(i))return;const label=document.createElement('label'), cb=document.createElement('input');
   cb.type='checkbox';cb.className='review-person';cb.dataset.index=i;cb.disabled=!c.seed;
   cb.addEventListener('change',()=>toggle(i));label.append(cb,document.createTextNode(' Person '+c.id+(!c.seed?' (ambiguous)':'')));list.append(label);
  });sync();
 }
 function selectFrame(i){
  frame=i;chosen=[];boat=null;field('frame').value=i;
  const nav=document.getElementById('review-boats');nav.replaceChildren();
  function add(text,index){const b=document.createElement('button');b.type='button';b.textContent=text;b.addEventListener('click',()=>{boat=index;chosen=[];people();});nav.append(b);}
  add('All people — confirm one boat manually',null);
  data.frames[i].boats.forEach((g,index)=>add('Suggested boat '+g.id+' · '+g.members.length+' people',index));
  image.onload=draw;image.src=data.frames[i].image;people();
 }
 canvas.addEventListener('click',event=>{
  if(!data)return;const r=canvas.getBoundingClientRect(),x=(event.clientX-r.left)/r.width,y=(event.clientY-r.top)/r.height;
  const hits=data.frames[frame].candidates.map((c,i)=>({c,i})).filter(({c,i})=>allowed(i)&&x>=c.box[0]&&x<=c.box[2]&&y>=c.box[1]&&y<=c.box[3]);
  if(hits.length===1)toggle(hits[0].i);else status.textContent='Use the labeled checkboxes for overlapping boxes.';
 });
 async function poll(){
  try{
   const res=await fetch('/review/status?clip='+encodeURIComponent(field('clip').value),{credentials:'same-origin'});
   if(!res.ok)throw Error('review_unavailable');const result=await res.json();
   if(result.state==='scanning'){setTimeout(poll,2000);return;}
   if(result.state!=='ready'){
    status.textContent=result.state==='model_unavailable'?'The local pose model/runtime is unavailable. Use manual selection below.':'Detection could not finish. Use manual selection below or reload after other work finishes.';return;
   }
   data=result;field('review').value=data.review;
   status.textContent='Review sampled frames and suggested boats. No rowers are selected yet.';
   const nav=document.getElementById('review-frames');
   data.frames.forEach((f,i)=>{const b=document.createElement('button');b.type='button';b.textContent=f.seconds.toFixed(2)+' s · '+f.candidates.length+' people';b.addEventListener('click',()=>selectFrame(i));nav.append(b);});
   const best=data.frames.reduce((bi,f,i)=>f.candidates.filter(c=>c.seed).length>data.frames[bi].candidates.filter(c=>c.seed).length?i:bi,0);
   selectFrame(best);
  }catch(e){status.textContent='Preview unavailable. Reload the review or return to the library; no analysis was started.';}
 }
 poll();
})();
"""
