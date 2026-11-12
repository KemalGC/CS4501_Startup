'use strict';
(() => {
 const panel=document.getElementById('quality-panel'), form=document.getElementById('quality-form');
 const status=document.getElementById('quality-state');let current=null,sequence=0;
 const dirty=value=>window.dispatchEvent(new CustomEvent('ss:quality-dirty',{detail:value}));
 const options=[['','Choose a response'],['1','1 — Very poor'],['2','2 — Poor'],['3','3 — Fair'],['4','4 — Good'],['5','5 — Excellent'],['cannot_judge','Cannot judge'],['not_applicable','Not applicable']];
 function clear(){current=null;sequence++;panel.hidden=true;form.reset();dirty(false);}
 window.addEventListener('ss:ready',event=>{
  const d=event.detail;
  if(!d.session||(location.pathname==='/library'&&!new URLSearchParams(location.search).has('clip')))clear();
 });
 window.addEventListener('ss:clip',async event=>{
  current=event.detail;const request=++sequence;const c=current.clip;panel.hidden=false;form.reset();dirty(false);
  document.getElementById('quality-clip').textContent='Report: '+c.title;
  status.textContent='Loading saved assessment…';const root=document.getElementById('quality-questions');root.replaceChildren();
  for(const q of current.questions){
   const label=document.createElement('label');label.className='quality-item';
   const title=document.createElement('strong');title.textContent=q.title;
   const sentence=document.createElement('span');sentence.textContent=q.question;
   const select=document.createElement('select');select.name=q.id;select.required=true;select.setAttribute('aria-label',q.title+' quality');
   for(const [value,text] of options){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
   label.append(title,sentence,select);root.append(label);
  }
  try{
   const response=await fetch('/api/quality?clip='+encodeURIComponent(c.id),{credentials:'same-origin'});const data=await response.json();
   if(!response.ok)throw Error('Could not restore quality ratings.');
   if(request!==sequence)return;
   const questionIds=new Set(current.questions.map(q=>q.id));
   const rows=data.responses.filter(r=>r.analysis_version===c.analysis.version&&r.questionnaire_version===current.version&&questionIds.has(r.question_id));
   for(const r of rows)form.elements.namedItem(r.question_id).value=r.reason==='rated'?String(r.score):r.reason;
   form.elements.comment.value=rows[0]?.comment||'';
   status.textContent=rows.length===current.questions.length?'Saved · edits replace this assessment':'No quality assessment saved yet';
  }catch(e){if(request===sequence)status.textContent=e.message;}
 });
 form.addEventListener('input',()=>{dirty(true);status.textContent='Unsaved quality answers';});
 form.onsubmit=async event=>{
  event.preventDefault();if(!current||!form.reportValidity())return;
  const request=sequence,answers={};for(const q of current.questions){const v=form.elements.namedItem(q.id).value;answers[q.id]=/^[1-5]$/.test(v)?Number(v):v;}
  const data={clip_id:current.clip.id,analysis_version:current.clip.analysis.version,questionnaire_version:current.version,answers,comment:form.elements.comment.value};
  const button=document.getElementById('quality-save');button.disabled=true;
  try{
   const response=await fetch('/api/quality',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':current.csrf},body:JSON.stringify(data)});
   const body=await response.json();if(!response.ok)throw Error((body.error||'Quality assessment was not saved.').replaceAll('_',' '));
   if(request===sequence){dirty(false);status.textContent='All quality answers saved';}
  }catch(e){if(request===sequence)status.textContent=e.message;}finally{button.disabled=false;}
 };
})();
