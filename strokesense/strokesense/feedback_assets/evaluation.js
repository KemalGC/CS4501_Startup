'use strict';
(() => {
 const $ = id => document.getElementById(id);
 const panel=$('evaluation-panel'),form=$('evaluation-form'),status=$('evaluation-state');
 const options=[['','Choose a judgment'],['correct','Correct'],['partly_correct','Partly correct'],['incorrect','Incorrect'],['cannot_judge','Cannot judge from this view'],['not_applicable','No applicable output']];
 let current=null,sequence=0,loading=false,saving=false;
 const dirty=value=>window.dispatchEvent(new CustomEvent('ss:evaluation-dirty',{detail:value}));
 function node(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
 function field(name){return form.elements.namedItem(name);}
 function setBusy(value){for(const element of form.querySelectorAll('input,select,textarea,button'))element.disabled=value;if(!value)manualEnabled();}
 function updateCount(){if(!current)return;const count=current.evaluation_questions.filter(q=>field(q.id)?.value).length;$('evaluation-progress').textContent=count+' / '+current.evaluation_questions.length+' answered';}
 function markDirty(){if(loading)return;dirty(true);status.textContent='Unsaved technical assessment';updateCount();}
 function capture(input){
  const detail={seconds:null};window.dispatchEvent(new CustomEvent('ss:source-time',{detail}));
  if(Number.isFinite(detail.seconds)&&current){input.value=Math.max(0,Math.min(current.clip.duration,detail.seconds)).toFixed(2);markDirty();previewMeasurement();}
 }
 function timestamp(name,label){
  const wrap=node('label',label);const input=node('input');input.type='number';input.name=name;input.min=0;input.max=current.clip.duration;input.step='any';input.placeholder='e.g. 3.25';
  wrap.append(input);return wrap;
 }
 function manualEnabled(){const enabled=field('manual_enabled').checked;$('evaluation-manual-fields').hidden=!enabled;for(const name of ['catch_count','first_catch_seconds','last_catch_seconds','rower_reference']){field(name).disabled=!enabled;field(name).required=enabled;}previewMeasurement();}
 function previewMeasurement(){
  const output=$('evaluation-rate-preview');
  if(!field('manual_enabled').checked){output.textContent='';return;}
  const count=Number(field('catch_count').value),start=Number(field('first_catch_seconds').value),end=Number(field('last_catch_seconds').value);
  const complete=['catch_count','first_catch_seconds','last_catch_seconds'].every(k=>field(k).value!=='');
  output.textContent=complete&&Number.isInteger(count)&&count>=2&&end>start?'Your manual estimate: '+(60*(count-1)/(end-start)).toFixed(1)+' strokes/min · '+(count-1)+' complete intervals':'Enter the first and last consecutive catch times and total catches counted.';
 }
 function clear(){current=null;sequence++;panel.hidden=true;loading=false;form.reset();dirty(false);}
 window.addEventListener('ss:ready',event=>{if(!event.detail.session||(location.pathname==='/library'&&!new URLSearchParams(location.search).has('clip')))clear();});
 window.addEventListener('ss:clip',async event=>{
  current=event.detail;const request=++sequence,c=current.clip;loading=true;panel.hidden=false;form.reset();dirty(false);
  $('evaluation-clip').textContent='Recording: '+c.title+' · analysis '+c.analysis.version.slice(0,12);
  status.textContent='Loading saved technical assessment…';const root=$('evaluation-questions');root.replaceChildren();
  for(const q of current.evaluation_questions){
   const box=node('section',undefined,'evaluation-item');const title=node('h3',q.title);title.id='evaluation-title-'+q.id;
   const help=node('p',q.question);help.id='evaluation-help-'+q.id;
   const select=node('select');select.name=q.id;select.required=true;select.setAttribute('aria-labelledby',title.id);select.setAttribute('aria-describedby',help.id);
   const absent=q.aspect_id&&['unavailable','not_run'].includes(c.analysis.aspects[q.aspect_id]?.status||'unavailable');
   for(const [value,text] of options){const option=node('option',text);option.value=value;option.disabled=absent&&['correct','partly_correct','incorrect'].includes(value);select.append(option);}
   box.append(title,help,select);
   if(absent)box.append(node('p','No model result is available for this criterion. Choose “No applicable output” or “Cannot judge.”','evaluation-unavailable'));
   const details=node('details');details.append(node('summary','Add a timestamp or correction (optional)'));
   const time=timestamp(q.id+'_time','Evidence time in this clip (seconds)');const button=node('button','Use current video time','quiet');button.type='button';button.onclick=()=>capture(time.querySelector('input'));
   const commentLabel=node('label','What did you observe?');const comment=node('textarea');comment.name=q.id+'_comment';comment.maxLength=500;comment.rows=2;comment.placeholder='Use a seat or clothing description, without athlete names.';commentLabel.append(comment);details.append(time,button,commentLabel);box.append(details);root.append(box);
  }
  for(const name of ['first_catch_seconds','last_catch_seconds'])field(name).max=c.duration;
  manualEnabled();updateCount();setBusy(true);
  try{
   const response=await fetch('/api/evaluation?clip='+encodeURIComponent(c.id),{credentials:'same-origin'}),data=await response.json();
   if(!response.ok)throw Error('Could not restore technical feedback. Reload before editing it.');
   if(request!==sequence)return;
   const saved=data.responses.find(r=>r.analysis_version===c.analysis.version&&r.questionnaire_version===current.evaluation_version);
   if(saved){for(const q of current.evaluation_questions){const answer=saved.answers[q.id];if(!answer)continue;field(q.id).value=answer.verdict;field(q.id+'_time').value=answer.timestamp_seconds??'';field(q.id+'_comment').value=answer.comment;}
    field('comment').value=saved.comment;const m=saved.stroke_measurement;if(m){field('manual_enabled').checked=true;for(const name of ['catch_count','first_catch_seconds','last_catch_seconds','rower_reference'])field(name).value=m[name];}
   }
   manualEnabled();updateCount();status.textContent=saved?'Saved · edits replace this assessment':'No technical assessment saved for this analysis yet';loading=false;setBusy(false);
  }catch(e){if(request===sequence){status.textContent=e.message;loading=true;}}
 });
 form.addEventListener('input',()=>{markDirty();previewMeasurement();});
 field('manual_enabled').addEventListener('change',manualEnabled);
 $('evaluation-first-time').onclick=()=>capture(field('first_catch_seconds'));
 $('evaluation-last-time').onclick=()=>capture(field('last_catch_seconds'));
 form.onsubmit=async event=>{
  event.preventDefault();if(!current||loading||saving||!form.reportValidity())return;
  const request=sequence,answers={};for(const q of current.evaluation_questions)answers[q.id]={verdict:field(q.id).value,timestamp_seconds:field(q.id+'_time').value===''?null:Number(field(q.id+'_time').value),comment:field(q.id+'_comment').value};
  const manual=field('manual_enabled').checked?{catch_count:Number(field('catch_count').value),first_catch_seconds:Number(field('first_catch_seconds').value),last_catch_seconds:Number(field('last_catch_seconds').value),rower_reference:field('rower_reference').value}:null;
  if(manual&&manual.last_catch_seconds<=manual.first_catch_seconds){status.textContent='The last catch must be after the first catch.';field('last_catch_seconds').focus();return;}
  const payload={clip_id:current.clip.id,analysis_version:current.clip.analysis.version,questionnaire_version:current.evaluation_version,answers,stroke_measurement:manual,comment:field('comment').value};
  saving=true;setBusy(true);
  try{
   const response=await fetch('/api/evaluation',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':current.csrf},body:JSON.stringify(payload)}),data=await response.json();
   if(!response.ok)throw Error((data.error||'Technical assessment was not saved.').replaceAll('_',' '));
   if(request===sequence){dirty(false);status.textContent='All technical judgments saved'+(data.stroke_measurement?' · manual estimate '+data.stroke_measurement.rate_spm.toFixed(1)+' strokes/min':'');}
  }catch(e){if(request===sequence)status.textContent=e.message;}finally{saving=false;if(request===sequence)setBusy(loading);}
 };
})();
