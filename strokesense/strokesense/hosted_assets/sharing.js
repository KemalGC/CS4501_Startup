'use strict';
(async()=>{
 const status=document.getElementById('status');
 const fragment=new URLSearchParams(location.hash.slice(1));
 const token=fragment.get('invite');
 // Clear the credential before any fetch. A URL fragment is not an HTTP query.
 if(location.hash)history.replaceState(null,'',location.pathname);
 if(location.pathname==='/join'){
  if(!token||fragment.size!==1){status.textContent='This invitation is incomplete. Ask the organizer for the full tester link.';return;}
  try{
   const config=await (await fetch('/api/hosting',{credentials:'same-origin'})).json();
   const response=await fetch('/api/redeem',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify({token})});
   const data=await response.json();if(!response.ok)throw Error(data.error||'Invitation failed');
   location.replace('/library');
  }catch(error){status.textContent=String(error.message).replaceAll('_',' ')+'. Ask the organizer for a working invitation.';}
  return;
 }
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
   document.getElementById('expires').textContent='Expires '+new Date(data.expires_utc*1000).toLocaleString()+'.';
   document.getElementById('owner-results').href='/library#owner='+encodeURIComponent(key);
   document.getElementById('owner').value='';result.hidden=false;
   status.textContent=data.readiness.clip_count+' recordings and '+data.readiness.report_count+' reports are ready for review. Share only the reviewer link below.';
  }catch(error){status.textContent=String(error.message).replaceAll('_',' ');}finally{button.disabled=false;}
 };
 document.getElementById('copy-link').onclick=async()=>{
  const field=document.getElementById('tester-link');
  try{await navigator.clipboard.writeText(field.value);status.textContent='Tester link copied. Send it only to invited reviewers.';}
  catch{field.focus();field.select();status.textContent='Select and copy the reviewer link. Clipboard access is unavailable in this browser.';}
 };
})();
