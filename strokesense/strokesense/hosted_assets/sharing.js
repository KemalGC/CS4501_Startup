'use strict';
(async()=>{
 const status=document.getElementById('status');
 const form=document.getElementById('invitation-form');
 if(!form)return;
 const result=document.getElementById('invitation-result');
 form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button'),key=document.getElementById('owner').value;
  button.disabled=true;result.hidden=true;status.textContent='Checking the report library…';
  try{
   const response=await fetch('/api/owner/invitation',{headers:{Authorization:'Bearer '+key},credentials:'same-origin'});
   const data=await response.json();
   if(!response.ok){if(data.readiness){status.textContent='Not ready: '+data.readiness.clip_count+' / '+data.readiness.expected_clips+' expected recordings; '+data.readiness.report_count+' saved reports. Restore missing media/reports before inviting testers.';return;}throw Error(data.error||'Invitation failed');}
   document.getElementById('tester-link').value=data.url;
   document.getElementById('expires').textContent='No reviewer login needed. Each person signs their own feedback with a name and consent.';
   document.getElementById('owner-results').href='/library#owner='+encodeURIComponent(key);
   document.getElementById('owner').value='';result.hidden=false;
   status.textContent=data.readiness.clip_count+' recordings and '+data.readiness.report_count+' reports are ready for review. Share only the reviewer link below.';
  }catch(error){status.textContent=String(error.message).replaceAll('_',' ');}finally{button.disabled=false;}
 };
 document.getElementById('copy-link').onclick=async()=>{
  const field=document.getElementById('tester-link');
  try{await navigator.clipboard.writeText(field.value);status.textContent='Survey link copied. Share with your reviewers.';}
  catch{field.focus();field.select();status.textContent='Select and copy the reviewer link. Clipboard access is unavailable in this browser.';}
 };
})();
