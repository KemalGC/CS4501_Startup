"""Visual and navigation enhancements for the Render-hosted StrokeSense demo.

This module only transforms the hosted HTML. It does not touch video uploads,
status polling, inference, the report content, or the private study.
"""

from __future__ import annotations

import json
import re


SITE_ORIGIN = "https://strokesense-review.vercel.app"

HOSTED_STYLE = r"""
/* StrokeSense navy-and-coral design, shared with the public Vercel site. */
:root{color-scheme:light;--ink:#07234a;--muted:#536780;--mint:#edf4fb;
 --accent:#e92c38;--ss-surface:#fff;--ss-canvas:#edf4fb;--ss-line:#dce6f0}
html[data-theme="dark"]{color-scheme:dark;--ink:#f2f7ff;--muted:#b2c6dd;
 --mint:#14365c;--accent:#ff6268;--ss-surface:#132e52;--ss-canvas:#081a36;--ss-line:#2e4c71}
body{background:var(--ss-canvas);color:var(--ink);font-family:'Plus Jakarta Sans',Inter,Segoe UI,system-ui,sans-serif}
header{background:#001e4a;padding:19px max(20px,calc((100vw - 1180px)/2));font-size:20px;letter-spacing:-.045em}
main{max-width:1210px;margin:25px auto;padding:0 22px 32px}
.hero{display:block;border-radius:22px;padding:32px 37px;margin-bottom:22px;color:white;
 background:radial-gradient(circle at 91% 4%,#165c91 0%,transparent 43%),linear-gradient(113deg,#001331,#001e4a 62%,#0c426f)}
.hero h1{color:white;font-size:clamp(30px,4.5vw,45px);font-weight:800;letter-spacing:-.055em;max-width:850px}
.hero .lede{font-size:16px;line-height:1.7;color:#dcebf9;margin:0}
.tag{color:#ff777d;font-size:12px;letter-spacing:.11em}
.clip-picker{background:var(--ss-surface);border-color:var(--ss-line);border-radius:18px;margin-bottom:11px}
.clip-tab{color:var(--ink);background:var(--ss-surface);border:1px solid var(--ss-line);border-radius:999px}
.clip-tab[aria-selected="true"]{background:#001e4a;color:#fff;border-color:#001e4a;box-shadow:none}
.clip-tab[aria-selected="true"] small{color:#d4e5f3}
.clip-tab small{color:var(--muted)}
.clip-add,.btn{border-radius:999px;background:linear-gradient(180deg,#ff575a,#db2432);font-family:inherit;
 box-shadow:0 8px 18px #aa17232e}
.clip-add:disabled,.btn:disabled{background:#8398ae;box-shadow:none}
.clip-remove{border-color:#e5c4c5;color:#aa333c;background:var(--ss-surface);border-radius:999px}
.clip-upload-status,.clip-privacy,.meta,small{color:var(--muted)}
.clip-privacy{font-size:13px;margin-bottom:23px}
.card{background:var(--ss-surface);border-color:var(--ss-line);border-radius:22px;box-shadow:0 15px 36px #001e4a0b}
.card h2{font-size:24px;letter-spacing:-.035em;color:var(--ink)}
.card p{line-height:1.65}
.status{color:var(--ink)}
.secondary{border:1px solid var(--ss-line);color:var(--ink);background:var(--mint);border-radius:999px;
 font-size:14px;transition:background-color .2s}
.secondary:hover{background:#d5eaf8}
html[data-theme="dark"] .secondary:hover{background:#1b446e}
.progress{background:var(--ss-line)}
.bar{background:linear-gradient(90deg,#166ca4,#ff444a)}
.note{background:var(--mint);border-left-color:#ff4147;color:var(--ink);border-radius:10px}
#details{color:var(--muted)}
.links a{margin-top:10px}
.inline-result{margin-top:23px;padding:23px;background:var(--ss-surface);border:1px solid var(--ss-line);
 border-radius:22px;box-shadow:0 15px 36px #001e4a0b}
.inline-result-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px}
.inline-result-head h2{margin:0;font-size:27px;color:var(--ink)}
.inline-result-close{border:1px solid var(--ss-line);border-radius:999px;padding:10px 18px;
 background:var(--mint);color:var(--ink);font-weight:800;cursor:pointer}
.inline-result iframe{display:block;width:100%;height:780px;border:1px solid var(--ss-line);
 border-radius:14px;background:#fff}
.inline-result video{max-height:640px;aspect-ratio:16/9;object-fit:contain}
footer{max-width:1210px;color:var(--muted);font-size:13px}
html.ss-embedded header{display:none}
html.ss-embedded main{margin-top:0;padding-top:0}
html.ss-embedded .hero{padding:25px 28px;margin:0 0 17px}
html.ss-embedded .hero h1{font-size:clamp(28px,3.1vw,39px)}
html.ss-embedded .hero .lede{font-size:14px}
@media(max-width:760px){main{padding:0 12px 26px}.hero{padding:26px 21px}
 .grid{grid-template-columns:1fr}.card{padding:17px}.inline-result{padding:14px}
 .inline-result iframe{height:660px}.inline-result-head h2{font-size:21px}}
"""

INLINE_VIEWER_HTML = """
<section class="inline-result" id="inline-result" aria-labelledby="inline-result-title" hidden>
 <div class="inline-result-head"><h2 id="inline-result-title">Coaching report</h2>
  <button id="inline-result-close" class="inline-result-close" type="button">Close result</button></div>
 <iframe id="inline-report" title="Generated StrokeSense coaching report" loading="eager" hidden></iframe>
 <video id="inline-overlay" controls playsinline preload="none" aria-label="Annotated rowing footage" hidden></video>
</section>
"""

HOSTED_SCRIPT = r"""
const ssHostOrigin='https://strokesense-review.vercel.app';
const ssResultSection=document.getElementById('inline-result');
const ssReportFrame=document.getElementById('inline-report');
const ssOverlayPlayer=document.getElementById('inline-overlay');
const ssResultHeading=document.getElementById('inline-result-title');
let ssParentReady=false;
function ssResultPath(link,kind){
  const url=new URL(link.href,window.location.href);
  const allowed=kind==='report'?'report':'annotated';
  if(url.origin!==window.location.origin||
     !new RegExp('^/demo(?:/videos/[a-f0-9]{48})?/'+allowed+'$').test(url.pathname))return null;
  return url.pathname;
}
function ssCloseResult(){
  ssResultSection.hidden=true;ssReportFrame.removeAttribute('src');
  ssOverlayPlayer.pause();ssOverlayPlayer.removeAttribute('src');ssOverlayPlayer.load();
  if(ssParentReady&&window.parent!==window){
    window.parent.postMessage({type:'strokesense:close-result'},ssHostOrigin);
  }
}
function ssShowResult(kind,path){
  ssCloseResult();
  ssResultSection.hidden=false;
  const theme=document.documentElement.dataset.theme==='dark'?'dark':'light';
  ssResultHeading.textContent=kind==='report'?'Your coaching report':'Annotated rowing video';
  if(kind==='report'){
    ssReportFrame.hidden=false;ssOverlayPlayer.hidden=true;
    ssReportFrame.src=path+'?theme='+theme;
  }else{
    ssReportFrame.hidden=true;ssOverlayPlayer.hidden=false;ssOverlayPlayer.src=path;
  }
  ssResultSection.scrollIntoView({behavior:'smooth',block:'start'});
}
window.addEventListener('message',(event)=>{
  if(event.origin!==ssHostOrigin||event.source!==window.parent||!event.data)return;
  if(event.data.type==='strokesense:host-ready')ssParentReady=true;
  if(event.data.type==='strokesense:theme'&&['dark','light'].includes(event.data.theme)){
    document.documentElement.dataset.theme=event.data.theme;
  }
});
if(window.self!==window.top)document.documentElement.classList.add('ss-embedded');
ssResultSection.hidden=true;
document.getElementById('inline-result-close').addEventListener('click',ssCloseResult);
for(const [kind,link] of [['report',reportLink],['annotated',overlay]]){
  link.removeAttribute('target');link.removeAttribute('rel');
  link.textContent=kind==='report'?'View coaching report':'View annotated video';
  link.addEventListener('click',(event)=>{
    const path=ssResultPath(link,kind);
    if(!path)return;event.preventDefault();
    if(ssParentReady&&window.parent!==window){
      window.parent.postMessage({type:'strokesense:show-result',kind,path},ssHostOrigin);
    }else ssShowResult(kind,path);
  });
}
"""

BRIDGE_SCRIPT = r"""
/* Only StrokeSense's Vercel frontend may drive the hosted API through this frame.
   All analysis, uploads and status calls remain same-origin requests to Render. */
const ssBridgeClientOrigins=[
  'https://strokesense-review.vercel.app',
  'https://strokesense-review-buh688zsc-stroke-sense.vercel.app',
  'https://strokesense-review-dnu9h8obu-stroke-sense.vercel.app',
  'https://strokesense-review-qa-stroke-sense.vercel.app'
];
function ssBridgeClip(id){
  if(id===null)return '';
  if(typeof id==='string'&&/^[a-f0-9]{48}$/.test(id))return '/videos/'+id;
  throw Error('invalid_video_id');
}
async function ssBridgeRequest(action,payload){
  const suffix=ssBridgeClip(payload.clipId===undefined?null:payload.clipId);
  if(action==='status'){
    const path=suffix?'/api/demo'+suffix+'/status':'/api/demo/status';
    const response=await fetch(path,{cache:'no-store',credentials:'same-origin'});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'status_failed');
    return result;
  }
  if(action==='dashboard'){
    const path=suffix?'/api/demo'+suffix+'/dashboard':'/api/demo/dashboard';
    const response=await fetch(path,{cache:'no-store',credentials:'same-origin'});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'dashboard_failed');
    return result;
  }
  if(action==='analyze'){
    const path=suffix?'/api/demo'+suffix+'/analyze':'/api/demo/analyze';
    const response=await fetch(path,{method:'POST',credentials:'same-origin',
      headers:{'content-type':'application/json','x-demo-csrf':token},body:'{}'});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'analysis_failed');
    return result;
  }
  if(action==='upload'){
    if(payload.clipId!==undefined&&payload.clipId!==null)throw Error('invalid_upload_request');
    const file=payload.file;
    if(!(file instanceof File)||file.size<1||file.size>50*1024*1024)throw Error('invalid_video_size');
    if(file.name.length<1||file.name.length>120)throw Error('invalid_video_name');
    const ext=(file.name.split('.').pop()||'').toLowerCase();
    const allowed={mp4:'video/mp4',mov:'video/quicktime',webm:'video/webm'};
    if(!allowed[ext])throw Error('unsupported_video_format');
    const response=await fetch('/api/demo/videos',{method:'POST',credentials:'same-origin',
      headers:{'content-type':allowed[ext],'x-demo-filename':encodeURIComponent(file.name),
        'x-demo-csrf':token},body:file});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'upload_failed');
    return result;
  }
  if(action==='delete'){
    if(!suffix)throw Error('cannot_delete_prepared_video');
    const deleteToken=payload.deleteToken;
    if(typeof deleteToken!=='string'||!/^[a-zA-Z0-9_-]{32,128}$/.test(deleteToken))
      throw Error('invalid_delete_token');
    const response=await fetch('/api/demo'+suffix,{method:'DELETE',credentials:'same-origin',
      headers:{'x-demo-csrf':token,'x-demo-delete-token':deleteToken}});
    const result=await response.json();
    if(!response.ok&&response.status!==404)throw Error(result.error||'delete_failed');
    return {deleted:true,expired:response.status===404};
  }
  throw Error('unsupported_action');
}
window.addEventListener('message',async(event)=>{
  if(!ssBridgeClientOrigins.includes(event.origin)||event.source!==window.parent||
     !event.data||event.data.type!=='strokesense:bridge-request')return;
  const requestId=event.data.id;
  if(!Number.isSafeInteger(requestId)||requestId<1)return;
  try{
    const result=await ssBridgeRequest(event.data.action,event.data);
    window.parent.postMessage({type:'strokesense:bridge-response',id:requestId,ok:true,result},
      event.origin);
  }catch(error){
    window.parent.postMessage({type:'strokesense:bridge-response',id:requestId,ok:false,
      error:String(error.message||'render_request_failed')},event.origin);
  }
});
if(window.parent!==window)for(const origin of ssBridgeClientOrigins)
  window.parent.postMessage({type:'strokesense:bridge-ready'},origin);
"""

REPORT_STYLE_LIGHT = """
<style>
:root{--ink:#07234a;--muted:#536780;--accent:#e92c38}
html{background:#f5f9fd!important;color-scheme:light}
body{background:#f5f9fd!important;color:#07234a!important;
 font-family:'Plus Jakarta Sans',Inter,Segoe UI,system-ui,sans-serif!important;
 line-height:1.65!important;max-width:1140px;margin:auto!important;padding:22px!important}
h1,h2,h3,h4{color:#001e4a!important;letter-spacing:-.035em}
h1{font-size:clamp(30px,4vw,45px)!important;line-height:1.15!important}
h2{border-bottom-color:#dce6f0!important}
a{color:#c92b39!important}
section,article,.card,.panel,table{border-radius:15px!important}
table{border-collapse:collapse;max-width:100%}
th{background:#001e4a!important;color:white!important}
td,th{border-color:#dce6f0!important}
img{max-width:100%;height:auto}
pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style>
"""

REPORT_STYLE_DARK = """
<style>
:root{--ink:#f2f7ff;--muted:#b2c6dd;--accent:#ff6268}
html{background:#081a36!important;color-scheme:dark}
body{background:#081a36!important;color:#f2f7ff!important;
 font-family:'Plus Jakarta Sans',Inter,Segoe UI,system-ui,sans-serif!important;
 line-height:1.65!important;max-width:1140px;margin:auto!important;padding:22px!important}
h1,h2,h3,h4{color:#f2f7ff!important;letter-spacing:-.035em}
h1{font-size:clamp(30px,4vw,45px)!important;line-height:1.15!important}
a{color:#ff777d!important}
section,article,.card,.panel,table{border-radius:15px!important}
table{border-collapse:collapse;max-width:100%}
th{background:#001e4a!important;color:white!important}
td,th{border-color:#2e4c71!important}
img{max-width:100%;height:auto}
pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style>
"""


def restyle_report(html: bytes, *, dark: bool = False) -> bytes:
    """Keep the model's full generated HTML, adding only a color/type layer."""
    original = html.decode("utf-8", errors="replace")
    css = REPORT_STYLE_DARK if dark else REPORT_STYLE_LIGHT
    if re.search(r"</head\s*>", original, flags=re.I):
        original = re.sub(r"</head\s*>", lambda m: css + m.group(0), original, count=1, flags=re.I)
    else:
        original = css + original
    return original.encode("utf-8")


def bridge_page(csrf: str, nonce: str) -> str:
    """Small, invisible protocol endpoint for the Vercel-native analyzer UI.

    No model state, cookies, or write methods are surfaced to arbitrary origins.
    API requests still use Render's existing CSRF, rate limits, and isolation.
    """
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>StrokeSense analysis connection</title></head><body>'
        '<script nonce="' + nonce + '">const token=' + json.dumps(csrf) + ';\n'
        + BRIDGE_SCRIPT + '</script></body></html>'
    )


def redesign_hosted_demo(page: str) -> str:
    """Embed responsive video/report viewing and relay results to Vercel."""
    required = (
        "</style>", "</main>", "const reportLink=document.getElementById('report-link');",
        "const overlay = document.getElementById('annotated');",
        "function activateClip(clip){", "refresh();setInterval(refresh,1200);",
    )
    if any(marker not in page for marker in required):
        raise ValueError("hosted_demo_ui_template_changed")
    page = page.replace("</style>", HOSTED_STYLE + "</style>", 1)
    page = page.replace("</main>", INLINE_VIEWER_HTML + "</main>", 1)
    page = page.replace("function activateClip(clip){", "function activateClip(clip){\n  ssCloseResult();", 1)
    page = page.replace("button.addEventListener('click',async()=>{",
                        "button.addEventListener('click',async()=>{\n ssCloseResult();", 1)
    page = page.replace("refresh();setInterval(refresh,1200);",
                        HOSTED_SCRIPT + BRIDGE_SCRIPT + "\nrefresh();setInterval(refresh,1200);", 1)
    return page
