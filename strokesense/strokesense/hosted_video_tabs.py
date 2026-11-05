"""Progressive enhancement for multiple real-analysis videos on the hosted demo.

The prepared clip remains the default. Visitor footage is uploaded to the
same-origin Render service, starts the same measured + LLM pipeline, and gains
its own tab. This module does not change the local-only oneclick demo.
"""

TABS_STYLE = r"""
.clip-picker{display:flex;align-items:center;justify-content:space-between;gap:16px;
  border:1px solid #cddfd6;border-radius:14px;background:#edf5f1;margin:0 0 20px;padding:14px 16px;flex-wrap:wrap}
.clip-tab-list{display:flex;align-items:center;gap:9px;flex:1;overflow-x:auto;padding:3px;min-width:230px}
.clip-tab{border:1px solid #a9c4b6;background:white;color:#1a4e40;font:700 15px system-ui;
  cursor:pointer;border-radius:9px;padding:12px 15px;white-space:nowrap;min-height:44px}
.clip-tab[aria-selected="true"]{border-color:#167b62;background:#d6eee3;box-shadow:inset 0 0 0 1px #167b62}
.clip-tab small{font-size:14px;font-weight:500;margin-left:5px;color:#54776b}
.clip-add{border:0;background:#0e776a;color:white;font:700 15px system-ui;border-radius:9px;
  cursor:pointer;padding:12px 17px;min-height:44px}
.clip-add:disabled{cursor:not-allowed;background:#708e84}
.clip-remove{border:1px solid #b96b66;background:#fff;color:#8a3230;font:700 14px system-ui;
  border-radius:9px;cursor:pointer;min-height:44px;padding:11px 15px}
.clip-remove:disabled{opacity:.55;cursor:not-allowed}
.clip-tab:focus-visible,.clip-add:focus-visible,.clip-remove:focus-visible{outline:3px solid #176f9d;outline-offset:2px}
.clip-upload-status{flex:1 1 100%;color:#33584b;font-size:14px;margin:0;min-height:0}
.clip-upload-status:empty{display:none}
.clip-privacy{margin:10px 0 16px;font-size:14px;color:#506a60}
@media(max-width:760px){.clip-picker{padding:12px}.clip-add{width:100%}.clip-remove{width:100%}}
"""

TABS_HTML = r"""
<section class="clip-picker" aria-label="Video analysis selection">
  <div id="clip-tab-list" class="clip-tab-list" role="tablist" aria-label="Videos">
    <button id="prepared-tab" class="clip-tab" type="button" role="tab"
            aria-selected="true" aria-controls="analysis-panel" data-clip="prepared">Prepared video <small>Default</small></button>
  </div>
  <button id="clip-add" class="clip-add" type="button">+ Upload new video</button>
  <button id="clip-remove" class="clip-remove" type="button" hidden>Remove selected video</button>
  <input id="clip-file" type="file" accept=".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm"
         aria-label="Choose a video for full analysis" hidden>
  <p id="clip-upload-status" class="clip-upload-status" role="status" aria-live="polite"></p>
</section>
<p class="clip-privacy">New videos run on Render automatically, with pose tracking, an annotated video, and an LLM coaching report. Temporary uploads may expire after two hours or when older uploads are replaced.</p>
"""

TABS_SCRIPT = r"""
const clipTabs=document.getElementById('clip-tab-list');
const defaultTab=document.getElementById('prepared-tab');
const clipInput=document.getElementById('clip-file');
const clipAdd=document.getElementById('clip-add');
const clipRemove=document.getElementById('clip-remove');
const uploadStatus=document.getElementById('clip-upload-status');
const clipPlayer=document.getElementById('clip-player');
const clipTitle=document.getElementById('video-title');
const clipMeta=document.getElementById('clip-meta');
const reportLink=document.getElementById('report-link');
const uploadedClips=[];
let activeVideoId=null;
let uploadInProgress=false;
let removeInProgress=false;
let pendingRemovalId=null;
let nextVideoNumber=2;
const clipOrigin='/demo/videos/';
const sampleClip={id:null,name:'Video Project 19 · 12.8-second eights clip',
  videoUrl:'/demo/video',reportUrl:'/demo/report',annotatedUrl:'/demo/annotated',
  info:'Full 12.8-second uploaded eights clip; the model runs on this footage. The report is computed from this exact video.'};
function statusEndpoint(){return activeVideoId?'/api/demo/videos/'+activeVideoId+'/status':'/api/demo/status';}
function analyzeEndpoint(){return activeVideoId?'/api/demo/videos/'+activeVideoId+'/analyze':'/api/demo/analyze';}
function activateClip(clip){
  activeVideoId=clip.id;
  pendingRemovalId=null;
  clipRemove.hidden=!clip.id;
  clipRemove.disabled=uploadInProgress||removeInProgress;
  clipRemove.textContent='Remove selected video';
  for(const item of clipTabs.querySelectorAll('[role="tab"]'))
    item.setAttribute('aria-selected',String(item.dataset.clip===(clip.id||'prepared')));
  clipTitle.textContent=clip.name;
  clipMeta.textContent=clip.info;
  clipPlayer.setAttribute('aria-label',clip.id?'Uploaded rowing video: '+clip.originalName:'Prepared eights video');
  if(clipPlayer.getAttribute('src')!==clip.videoUrl){clipPlayer.pause();clipPlayer.setAttribute('src',clip.videoUrl);clipPlayer.load();}
  reportLink.href=clip.reportUrl;
  overlay.href=clip.annotatedUrl;
  links.hidden=true;crew.hidden=true;bar.style.width='0';
  status.textContent='Checking analysis…';details.textContent='Fetching the current report status from Render.';
  uploadStatus.textContent='';
  refresh();
}
defaultTab.addEventListener('click',()=>activateClip(sampleClip));
function rememberClips(){
  try{localStorage.setItem('strokesense-render-videos',JSON.stringify(uploadedClips.slice(-3).map(({id,originalName,deleteToken})=>({id,name:originalName,deleteToken}))));}
  catch(e){} // Third-party iframe storage may be unavailable.
}
function createClip(id,name,deleteToken){
  if(!/^[a-f0-9]{48}$/.test(id)||typeof name!=='string'||!name||name.length>120)return null;
  if(deleteToken!==undefined&&deleteToken!==null&&!/^[a-zA-Z0-9_-]{32,128}$/.test(deleteToken))return null;
  const found=uploadedClips.find(item=>item.id===id);if(found)return found;
  if(uploadedClips.length>=3){
    const evicted=uploadedClips.shift();
    clipTabs.querySelector('[data-clip="'+evicted.id+'"]')?.remove();
  }
  const index=nextVideoNumber++;
  const clip={id,name:'Video '+index+' · '+name,originalName:name,deleteToken:deleteToken||null,
    videoUrl:clipOrigin+id+'/video',reportUrl:clipOrigin+id+'/report',annotatedUrl:clipOrigin+id+'/annotated',
    info:'Uploaded footage: '+name+'. Full model analysis runs on Render; measurements and LLM coaching appear in the report when finished.'};
  const tab=document.createElement('button');tab.type='button';tab.className='clip-tab';
  tab.setAttribute('role','tab');tab.setAttribute('aria-selected','false');
  tab.setAttribute('aria-controls','analysis-panel');tab.dataset.clip=id;
  tab.textContent='Video '+index;tab.title=name;tab.addEventListener('click',()=>activateClip(clip));
  clipTabs.appendChild(tab);uploadedClips.push(clip);return clip;
}
try{
  const previous=JSON.parse(localStorage.getItem('strokesense-render-videos')||'[]');
  if(Array.isArray(previous))for(const item of previous.slice(-3))createClip(item.id,item.name,item.deleteToken);
}catch(e){}
clipRemove.addEventListener('click',async()=>{
  const clip=uploadedClips.find(item=>item.id===activeVideoId);
  if(!clip||removeInProgress||uploadInProgress)return;
  if(pendingRemovalId!==clip.id){
    pendingRemovalId=clip.id;
    clipRemove.textContent='Confirm removal';
    uploadStatus.textContent='Click Confirm removal again to permanently delete '+clip.originalName+' and its analysis results from Render.';
    return;
  }
  removeInProgress=true;clipRemove.disabled=true;clipAdd.disabled=true;
  uploadStatus.textContent='Removing '+clip.originalName+' and its analysis from Render…';
  try{
    const response=await fetch('/api/demo/videos/'+clip.id,{method:'DELETE',credentials:'same-origin',
      headers:{'x-demo-csrf':token,'x-demo-delete-token':clip.deleteToken||''}});
    const result=await response.json();
    if(!response.ok&&response.status!==404){
      throw Error(result.error==='analysis_in_progress'?'Please wait for the current analysis to finish before removing this video.':
        'Could not remove this video from Render. Please retry.');
    }
    const at=uploadedClips.findIndex(item=>item.id===clip.id);
    if(at!==-1)uploadedClips.splice(at,1);
    clipTabs.querySelector('[data-clip="'+clip.id+'"]')?.remove();
    rememberClips();
    if(activeVideoId===clip.id)activateClip(sampleClip);
    uploadStatus.textContent=response.status===404?'The expired video tab was removed.':
      'Removed '+clip.originalName+' and its analysis from Render.';
  }catch(error){uploadStatus.textContent=error.message||'Removal failed. Please retry.';}
  finally{
    removeInProgress=false;pendingRemovalId=null;clipAdd.disabled=false;
    clipRemove.textContent='Remove selected video';
    if(!clipRemove.hidden)clipRemove.disabled=false;
    refresh();
  }
});
clipAdd.addEventListener('click',()=>{clipInput.value='';clipInput.click();});
clipInput.addEventListener('change',async()=>{
  const file=clipInput.files&&clipInput.files[0];if(!file)return;
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  const mimes={mp4:'video/mp4',mov:'video/quicktime',webm:'video/webm'};
  if(!mimes[ext]||!file.size||file.size>50*1024*1024){
    uploadStatus.textContent='Choose a nonempty MP4, MOV or WebM video no larger than 50 MB.';return;
  }
  uploadInProgress=true;clipAdd.disabled=true;clipRemove.disabled=true;button.disabled=true;
  uploadStatus.textContent='Uploading '+file.name+' to Render…';
  try{
    const response=await fetch('/api/demo/videos',{method:'POST',credentials:'same-origin',
      headers:{'content-type':mimes[ext],'x-demo-filename':encodeURIComponent(file.name),'x-demo-csrf':token},body:file});
    const result=await response.json();
    if(!response.ok){
      const message=result.error==='analysis_in_progress'?'Render is analyzing another video. Wait for it to finish and retry.':
        result.error==='upload_in_progress'?'Another video is uploading right now. Please retry in a few seconds.':
        result.error==='analysis_capacity_reached'?'The analyzer is at capacity. Retry after the current job finishes.':
        result.error==='video_too_large'?'This video exceeds the 50 MB limit.':
        result.error==='invalid_video_container'?'The selected file is not a supported video container.':
        result.error==='upload_rate_limited'?'The demo has reached its current upload limit. Please try again later.':
        'Render could not accept this video. Please retry.';
      throw Error(message);
    }
    const clip=createClip(result.id,result.name,result.delete_token);
    if(!clip)throw Error('The analyzer did not return a valid video record.');
    rememberClips();activateClip(clip);
    uploadStatus.textContent=result.queued?'Uploaded successfully. Your video is queued; Render will start full analysis automatically when the current job finishes.':
      'Uploaded. Render is automatically running pose analysis and preparing your report.';
  }catch(error){uploadStatus.textContent=error.message||'Upload failed. Please retry.';}
  finally{uploadInProgress=false;clipAdd.disabled=false;clipRemove.disabled=false;button.disabled=false;refresh();}
});
"""


def add_video_tabs(page: str) -> str:
    """Inject one accessible tab strip and wire the existing report UI per job."""
    required = ('</style>', '<div class="grid">', 'src="/demo/video"',
                'href="/demo/report"', '<p class="meta">',
                "const crew = document.getElementById('crew-summary');",
                "fetch('/api/demo/status'", "fetch('/api/demo/analyze'")
    if any(snippet not in page for snippet in required):
        raise ValueError('hosted_demo_template_changed')
    page = page.replace('</style>', TABS_STYLE + '</style>', 1)
    page = page.replace('<div class="grid">', TABS_HTML + '<div id="analysis-panel" role="tabpanel" class="grid">', 1)
    page = page.replace('src="/demo/video"', 'id="clip-player" src="/demo/video"', 1)
    page = page.replace('href="/demo/report"', 'id="report-link" href="/demo/report"', 1)
    page = page.replace('<p class="meta">', '<p id="clip-meta" class="meta">', 1)
    page = page.replace("const crew = document.getElementById('crew-summary');",
        "const crew = document.getElementById('crew-summary');\n" + TABS_SCRIPT, 1)
    page = page.replace("fetch('/api/demo/status'", 'fetch(statusEndpoint()', 1)
    page = page.replace("fetch('/api/demo/analyze'", 'fetch(analyzeEndpoint()', 1)
    page = page.replace("async function refresh(){", "async function refresh(){\n if(uploadInProgress)return;\n const requestedVideoId=activeVideoId;", 1)
    page = page.replace("if(!response.ok)throw Error('Status request failed');", """if(requestedVideoId!==activeVideoId)return;
  if(response.status===404&&requestedVideoId){
    links.hidden=true;crew.hidden=true;button.disabled=true;
    status.textContent='This uploaded video has expired';
    details.textContent='Temporary uploads are removed to free Render storage. Upload your video again to run a fresh analysis.';
    return;
  }
  if(!response.ok)throw Error('Status request failed');""", 1)
    page = page.replace("const data=await response.json();", "const data=await response.json();\n  if(requestedVideoId!==activeVideoId)return;", 1)
    page = page.replace("}catch(e){status.textContent='Unable to connect to the analysis service'", "}catch(e){if(requestedVideoId!==activeVideoId)return;status.textContent='Unable to connect to the analysis service'", 1)
    page = page.replace("button.disabled=data.state==='running'||data.can_rerun===false;",
        "button.disabled=uploadInProgress||data.state==='running'||data.can_rerun===false;\n  clipRemove.disabled=uploadInProgress||removeInProgress||data.state==='running'||(data.can_rerun===false&&data.state!=='queued');", 1)
    return page
