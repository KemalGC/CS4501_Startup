'use strict';
(() => {
 const $ = id => document.getElementById(id);
 const state = {data:null, clip:0, aspect:0, saved:{}, submitted:{}, dirty:false, mode:'video', load:0, owner:''};
 const shortNames = {tracking:'Tracking',rate:'Stroke rate',position:'Body position',sequencing:'Sequencing',timing:'Crew timing',evidence:'Evidence'};
 const useLabels=['Not useful','Slightly useful','Moderately useful','Very useful','Extremely useful'];
 const accLabels=['Clearly wrong','Mostly wrong','Mixed','Mostly right','Clearly right'];
 let toastTimer;
 let qualityDirty=false,evaluationDirty=false;
 window.addEventListener('ss:evaluation-dirty',e=>{evaluationDirty=!!e.detail;});
 window.addEventListener('ss:quality-dirty',e=>{qualityDirty=!!e.detail;});
 function toast(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
 async function api(path,{method='GET',body,owner=false}={}){
  const headers={};if(state.data)headers['X-CSRF-Token']=state.data.csrf;
  if(body!==undefined)headers['Content-Type']='application/json';
  if(owner)headers.Authorization='Bearer '+state.owner;
  const response=await fetch(path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error((data.error||'Request failed').replaceAll('_',' '));return data;
 }
 const clip=()=>state.data.clips[state.clip];
 function updateVideoSubmit(){if(!state.data?.session||!state.data.clips.length)return;const c=clip();$('video-submit-status').textContent=state.submitted[c.id]===c.analysis.version?'Submitted · you may submit again after edits':'Not submitted yet';$('video-submit-progress').textContent=Object.keys(state.saved).length+' of 6 aspect responses saved; quality and technical sections are separate and optional.';}
 const aspect=()=>state.data.aspects[state.aspect];
 const asset=(kind)=>'/asset/'+encodeURIComponent(clip().id)+'/'+kind;
 function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
 function hasUnsaved(){return (state.dirty||qualityDirty||evaluationDirty)&&!confirm('You have unsaved ratings. Leave this aspect without saving?');}
 function renderScale(id,name,labels){
  const box=$(id);box.replaceChildren();labels.forEach((text,i)=>{const label=el('label');const input=document.createElement('input');input.type='radio';input.name=name;input.value=i+1;input.required=true;input.setAttribute('aria-label',name+' '+(i+1)+' — '+text);label.append(input,el('span',String(i+1),'number'),el('span',text,'scale-label'));box.append(label);});
 }
 function renderLibrary(){
  $('clips').replaceChildren();$('library-count').textContent=state.data.clips.length+' uploads · submit any number of videos';
  state.data.clips.forEach((c,i)=>{const b=el('button',undefined,'clip-card'+(i===state.clip?' active':''));b.type='button';b.setAttribute('aria-pressed',String(i===state.clip));
   if(c.assets.includes('poster')){const img=document.createElement('img');img.src='/asset/'+c.id+'/poster';img.alt='Preview of '+c.title;img.loading='lazy';b.append(img);}
   b.append(el('strong',c.title));if(state.submitted[c.id]===c.analysis.version)b.append(el('span','Submitted','badge'));const meta=el('small');meta.append(el('span',Math.round(c.duration)+' sec'),el('span',c.analysis.status==='provisional'?'Model output':'Limitations'));b.append(meta);b.addEventListener('click',()=>{if(!hasUnsaved())chooseClip(i);});$('clips').append(b);
  });
 }
 function renderAspects(){
  $('aspect-tabs').replaceChildren();state.data.aspects.forEach((a,i)=>{const b=el('button',shortNames[a.id],'aspect-tab'+(i===state.aspect?' active':'')+(state.saved[a.id]?' saved':''));b.type='button';b.setAttribute('aria-pressed',String(i===state.aspect));b.onclick=()=>{if(!hasUnsaved()){state.aspect=i;renderAspect();}};$('aspect-tabs').append(b);});
  $('progress').textContent=Object.keys(state.saved).length+' / '+state.data.aspects.length+' saved';if(state.data.session&&!$('video-submit-panel').hidden)updateVideoSubmit();
 }
 function renderAspect(){
  renderAspects();const a=aspect(),c=clip(),f=c.analysis.aspects[a.id];
  $('aspect-title').textContent=a.title;$('aspect-question').textContent=a.question;$('finding-title').textContent=a.title;$('finding-summary').textContent=f.summary||'No result was released.';
  const absent=['unavailable','not_run'].includes(f.status);$('finding-status').textContent=absent?'No result to judge':'Candidate output';$('finding-status').className='badge'+(absent?' warning':'');
  const details=$('finding-details');details.replaceChildren();
  if(Array.isArray(f.details)&&f.details.length){const list=el('ul',undefined,'details-list');for(const d of f.details){const li=el('li');if(typeof d==='string'){li.append(el('span',d));}else{li.append(el('span',String(d.label)),el('strong',String(d.value)));}list.append(li);}details.append(list);}
  const form=$('rating-form');form.reset();$('save-state').textContent='';$('no-accuracy').hidden=!absent;
  form.querySelectorAll('[name=accuracy]').forEach(input=>{input.disabled=absent&&/^\d$/.test(input.value);});
  const saved=state.saved[a.id];if(saved){
   const u=saved.usefulness===null?'na':String(saved.usefulness),ac=saved.accuracy===null?saved.accuracy_reason:String(saved.accuracy);
   form.querySelector('[name=usefulness][value="'+u+'"]').checked=true;
   const radio=form.querySelector('[name=accuracy][value="'+ac+'"]');if(radio&&!radio.disabled)radio.checked=true;
   form.elements.comment.value=saved.comment;form.elements.timestamp.value=saved.timestamp_seconds??'';$('save-state').textContent='Saved · edits replace this response';
  }else if(absent){form.querySelector('[name=accuracy][value=not_applicable]').checked=true;}
  form.elements.timestamp.max=c.duration;state.dirty=false;
 }
 async function chooseClip(i){
  state.clip=i;state.aspect=0;state.saved={};state.dirty=false;const seq=++state.load;const c=clip();state.mode=c.assets.includes('annotated')?'annotated':'video';
  $('video-submit-panel').hidden=false;$('video-submit-success').hidden=true;
  $('video-submit-status').textContent='';$('video-submit-progress').textContent='';
  $('clip-title').textContent=c.title;$('analysis-badge').textContent=c.analysis.status==='provisional'?'Provisional model analysis':'Insufficient model evidence';$('analysis-badge').className='badge'+(c.analysis.status==='provisional'?'':' warning');
  $('annotated-mode').hidden=!c.assets.includes('annotated');$('report-toggle').hidden=!c.assets.includes('report');$('report-panel').hidden=true;$('report-frame').removeAttribute('src');$('report-direct').href=asset('report');
  const w=c.analysis.window;$('method').textContent=(c.analysis.method||'')+(w?' · Analyzed source window: '+w.start.toFixed(1)+'–'+w.end.toFixed(1)+' s. ':' ')+(c.analysis.note||'')+' Study preview is silent; evaluate the visible evidence, not audio.';
  $('video').poster=c.assets.includes('poster')?asset('poster'):'';$('video').src=asset(state.mode);$('video').load();setModeButtons();renderLibrary();renderAspect();
  updateVideoSubmit();window.dispatchEvent(new CustomEvent('ss:clip',{detail:{clip:c,csrf:state.data.csrf,questions:state.data.quality_questions,version:state.data.quality_version,evaluation_questions:state.data.evaluation_questions,evaluation_version:state.data.evaluation_version}}));
  try{const got=await api('/api/responses?clip='+encodeURIComponent(c.id));if(seq!==state.load)return;state.saved=Object.fromEntries(got.responses.filter(r=>r.analysis_version===c.analysis.version).map(r=>[r.aspect_id,r]));renderAspect();}catch(e){toast(e.message,true);}
 }
 function sourceTime(){return $('video').currentTime+(state.mode==='annotated'?(clip().analysis.window?.start||0):0);}
 window.addEventListener('ss:source-time',event=>{if(state.data?.session&&state.data.clips.length)event.detail.seconds=sourceTime();});
 function setModeButtons(){$('source-mode').classList.toggle('active',state.mode==='video');$('annotated-mode').classList.toggle('active',state.mode==='annotated');}
 function changeMode(mode){const time=sourceTime();state.mode=mode;const video=$('video');video.src=asset(mode);video.load();video.addEventListener('loadedmetadata',()=>{video.currentTime=Math.max(0,Math.min(video.duration||0,time-(mode==='annotated'?(clip().analysis.window?.start||0):0)));},{once:true});setModeButtons();}
 function capture(){const t=Math.min(clip().duration,sourceTime());$('rating-form').elements.timestamp.value=t.toFixed(2);state.dirty=true;toast('Source timestamp '+t.toFixed(2)+' s attached to this aspect.');}
 async function bootstrap(){
  try{state.data=await api('/api/bootstrap');$('welcome').hidden=!!state.data.session;$('workspace').hidden=!state.data.session;$('next-reviewer').hidden=!state.data.session;
   if(state.data.session){state.submitted=Object.fromEntries((state.data.submissions||[]).map(x=>[x.clip_id,x.analysis_version]));$('reviewer-label').textContent='Reviewing as '+(state.data.session.display_name||'anonymous historical session');}
   else{state.submitted={};$('video-submit-panel').hidden=true;}
   if(state.data.session&&state.data.clips.length&&(location.pathname!=='/library'||new URLSearchParams(location.search).has('clip'))){const wanted=new URLSearchParams(location.search).get('clip');const requested=state.data.clips.findIndex(c=>c.id===wanted);await chooseClip(requested>=0?requested:Math.min(state.clip,state.data.clips.length-1));if(wanted&&requested<0)toast('That recording is no longer in the study. Choose one from the library.',true);}
   window.dispatchEvent(new CustomEvent('ss:ready',{detail:state.data}));
   if(state.owner){$('owner').hidden=false;await loadOwner();}
  }catch(e){toast('Could not load the study: '+e.message,true);}
 }
 async function loadOwner(){
  try{const d=await api('/api/owner/summary',{owner:true});$('owner-stats').replaceChildren();
   [[d.submitted_video_count||d.submitted_videos_count||0,'Video reviews submitted'],[d.reviewer_count,'Reviewers with aspect feedback'],[d.response_count,'Aspect reviews saved'],[d.technical_evaluation?.assessment_count||0,'Technical assessments saved'],[d.technical_evaluation?.manual_measurement_count||0,'Manual cadence observations']].forEach(([n,t])=>{const card=el('div',undefined,'stat-card');card.append(el('strong',String(n)),el('span',t));$('owner-stats').append(card);});
   const root=$('owner-table');root.replaceChildren();if(!d.aspects.length){root.append(el('p','No aspect-level feedback yet. Technical judgments and report-quality answers are available in their separate exports.','empty-state'));return;}
   const table=el('table'),head=el('tr');['Recording / aspect','Usefulness','Perceived accuracy','Cannot judge','Not applicable'].forEach(t=>head.append(el('th',t)));table.append(head);
   d.aspects.forEach(r=>{const row=el('tr');const c=state.data.clips.find(c=>c.id===r.clip_id);const cells=[(c?.title||r.clip_id)+' / '+shortNames[r.aspect_id],r.usefulness_n?r.usefulness_mean.toFixed(2)+' / 5 · n='+r.usefulness_n:'— · n=0',r.accuracy_n?r.accuracy_mean.toFixed(2)+' / 5 · n='+r.accuracy_n:'— · n=0',r.cannot_judge_n,r.not_applicable_n];cells.forEach(t=>row.append(el('td',String(t))));table.append(row);});root.append(table);
  }catch(e){toast('Owner dashboard: '+e.message,true);}
 }
 async function exportData(ext,quality=false,evaluation=false,submissions=false){try{const r=await fetch('/api/owner/'+(submissions?'submissions.':evaluation?'evaluation.':quality?'quality.':'export.')+ext,{headers:{Authorization:'Bearer '+state.owner},credentials:'same-origin'});if(!r.ok)throw Error('Owner key required');const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=(submissions?'strokesense-submissions.':evaluation?'strokesense-technical-evaluation.':quality?'strokesense-quality.':'strokesense-feedback.')+ext;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){toast(e.message,true);}}
 renderScale('usefulness-scale','usefulness',useLabels);renderScale('accuracy-scale','accuracy',accLabels);
 const hash=new URLSearchParams(location.hash.slice(1));if(hash.has('owner')){state.owner=hash.get('owner');sessionStorage.setItem('ss_owner',state.owner);history.replaceState(null,'',location.pathname);}else state.owner=sessionStorage.getItem('ss_owner')||'';
 window.addEventListener('hashchange',()=>{const params=new URLSearchParams(location.hash.slice(1));if(params.has('owner')){state.owner=params.get('owner');sessionStorage.setItem('ss_owner',state.owner);history.replaceState(null,'',location.pathname);$('owner').hidden=false;loadOwner();}});
 $('enroll').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;try{await api('/api/session',{method:'POST',body:{role:form.elements.role.value,experience:form.elements.experience.value,consent:form.elements.consent.checked,display_name:form.elements.display_name.value}});await bootstrap();($('reports-library').hidden?$('workspace'):$('reports-library')).scrollIntoView({block:'start',behavior:'smooth'});}catch(e){toast(e.message,true);}};
 $('rating-form').addEventListener('input',()=>{state.dirty=true;$('save-state').textContent='Unsaved changes';});
 $('rating-form').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;
  const u=form.querySelector('[name=usefulness]:checked')?.value,a=form.querySelector('[name=accuracy]:checked')?.value;
  if(!u||!a){toast('Choose both a usefulness rating and an accuracy response.',true);return;}
  const current=aspect().id;const payload={clip_id:clip().id,analysis_version:clip().analysis.version,aspect_id:current,usefulness:u==='na'?null:Number(u),accuracy:/^\d$/.test(a)?Number(a):null,accuracy_reason:/^\d$/.test(a)?'rated':a,comment:form.elements.comment.value,timestamp_seconds:form.elements.timestamp.value===''?null:Number(form.elements.timestamp.value)};
  $('save-button').disabled=true;
  try{await api('/api/reviews',{method:'POST',body:payload});state.saved[current]=payload;state.dirty=false;const next=state.data.aspects.findIndex((x,i)=>i>state.aspect&&!state.saved[x.id]);if(next>=0)state.aspect=next;renderAspect();toast(Object.keys(state.saved).length===6?'Six aspects saved. Continue with the technical checklist and five quality questions below.':'Feedback saved.');if(state.owner)loadOwner();}catch(e){toast(e.message,true);}finally{$('save-button').disabled=false;}
 };

 async function submitCurrentVideo(){
  if(!state.data?.session||!state.data.clips.length)return;
  if(state.dirty||qualityDirty||evaluationDirty){toast('Save your edited aspect, quality or technical answers before submitting this video.',true);$('submit-video-status').textContent='Unsaved changes must be saved first.';return;}
  const c=clip(),btn=$('submit-video');btn.disabled=true;$('submit-video-status').textContent='Submitting saved feedback…';
  try{
   const result=await api('/api/submit-video',{method:'POST',body:{clip_id:c.id,analysis_version:c.analysis.version}});
   state.submitted[c.id]=c.analysis.version;$('video-submit-success').hidden=false;
   $('submit-video-status').textContent='Submitted '+new Date(result.submitted_utc).toLocaleString()+
      ' · '+result.saved.aspect_count+' aspect(s), '+result.saved.quality_count+' quality answer(s), '+result.saved.technical_count+' technical assessment(s).';
   renderLibrary();toast('This video is submitted. You can stop here or review another.');
  }catch(e){$('submit-video-status').textContent=e.message;toast(e.message,true);}finally{btn.disabled=false;}
 }
 $('submit-video').onclick=submitCurrentVideo;
 $('submit-next').onclick=()=>{if(!hasUnsaved()){chooseClip((state.clip+1)%state.data.clips.length);$('workspace').scrollIntoView({block:'start',behavior:'smooth'});}};
 $('submit-finish').onclick=()=>{$('next-reviewer').click();};
 $('capture-time').onclick=capture;$('clear-time').onclick=()=>{$('rating-form').elements.timestamp.value='';state.dirty=true;};
 $('video').addEventListener('timeupdate',()=>{$('video-time').textContent='Source time '+sourceTime().toFixed(2)+' s'+(state.mode==='annotated'?' · model overlay':'');});
 $('source-mode').onclick=()=>changeMode('video');$('annotated-mode').onclick=()=>changeMode('annotated');
 window.addEventListener('ss:open-report',()=>{if(state.data?.session&&clip()?.assets.includes('report')){$('report-panel').hidden=false;$('report-frame').src=asset('report');$('report-direct').href=asset('report');}});
 $('report-toggle').onclick=()=>{const panel=$('report-panel');panel.hidden=!panel.hidden;if(!panel.hidden){$('report-frame').src=asset('report');panel.scrollIntoView({block:'start',behavior:'smooth'});}};
 $('next-clip').onclick=()=>{if(!hasUnsaved())chooseClip((state.clip+1)%state.data.clips.length);};
 $('withdraw').onclick=async()=>{if(!confirm('Permanently delete all feedback from your current reviewer session?'))return;try{await api('/api/withdraw',{method:'POST',body:{}});state.saved={};state.dirty=false;await bootstrap();toast('Your saved feedback has been withdrawn.');}catch(e){toast(e.message,true);}};
 $('next-reviewer').onclick=async()=>{if(hasUnsaved())return;if(!confirm('Finish this session? Saved feedback stays in the study. Use “Withdraw my feedback” instead to delete it.'))return;try{await api('/api/end-session',{method:'POST',body:{}});state.owner='';sessionStorage.removeItem('ss_owner');$('owner').hidden=true;state.saved={};state.dirty=false;await bootstrap();$('enroll').reset();window.scrollTo(0,0);}catch(e){toast(e.message,true);}};
 $('refresh-owner').onclick=loadOwner;$('export-submissions-csv').onclick=()=>exportData('csv',false,false,true);$('export-submissions-json').onclick=()=>exportData('json',false,false,true);$('export-csv').onclick=()=>exportData('csv');$('export-json').onclick=()=>exportData('json');
 $('export-evaluation-csv').onclick=()=>exportData('csv',false,true);$('export-evaluation-json').onclick=()=>exportData('json',false,true);
 $('export-quality-csv').onclick=()=>exportData('csv',true);$('export-quality-json').onclick=()=>exportData('json',true);
 window.addEventListener('beforeunload',event=>{if(state.dirty||qualityDirty||evaluationDirty){event.preventDefault();event.returnValue='';}});
 bootstrap();
})();
