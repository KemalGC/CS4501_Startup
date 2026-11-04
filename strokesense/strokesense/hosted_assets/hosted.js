'use strict';
(async()=>{
 const status=document.getElementById('status');
 try{
  const config=await (await fetch('/api/hosting',{credentials:'same-origin'})).json();
  const access=document.getElementById('access');
  if(access)access.onsubmit=async e=>{e.preventDefault();const b=access.querySelector('button');b.disabled=true;
   try{const r=await fetch('/api/access',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify({code:document.getElementById('code').value})});
    if(!r.ok)throw Error((await r.json()).error);location.reload();
   }catch(err){status.textContent=String(err.message).replaceAll('_',' ');}finally{b.disabled=false;}};
  const setup=document.getElementById('setup');
  if(setup){
   if(config.study_ready){status.textContent='A study is already installed. Replacing it here is disabled to protect feedback.';setup.querySelector('button').disabled=true;}
   setup.onsubmit=e=>{e.preventDefault();const file=document.getElementById('pack').files[0],key=document.getElementById('owner').value,b=setup.querySelector('button');
    if(!file||file.size>750*1024*1024){status.textContent='Choose the complete study ZIP, at most 750 MiB.';return;}
    b.disabled=true;const progress=document.getElementById('progress');progress.hidden=false;
    const xhr=new XMLHttpRequest();xhr.open('POST','/api/setup');xhr.setRequestHeader('Content-Type','application/zip');xhr.setRequestHeader('Authorization','Bearer '+key);xhr.setRequestHeader('X-CSRF-Token',config.csrf);
    xhr.upload.onprogress=event=>{if(event.lengthComputable){progress.value=100*event.loaded/event.total;status.textContent=Math.round(progress.value)+'% uploaded'+(progress.value===100?' — validating study files…':'');}};
    xhr.onerror=()=>{status.textContent='Upload interrupted. Reload to check whether setup completed before retrying.';b.disabled=false;};
    xhr.onload=()=>{let result;try{result=JSON.parse(xhr.responseText);}catch{status.textContent='Host rejected the upload. Check Render logs or use the authenticated SCP transfer described in RENDER_DEPLOY.md.';b.disabled=false;return;}
     if(xhr.status!==201){status.textContent=String(result.error||'Upload failed').replaceAll('_',' ');b.disabled=false;return;}
     status.textContent=result.clip_count+' clips installed. Share the library address and the separate reviewer code.';
     const a=document.createElement('a');a.href='/#owner='+encodeURIComponent(key);a.textContent='Open private owner dashboard';
     const box=document.getElementById('owner-link');box.replaceChildren(a);box.hidden=false;
     document.getElementById('owner').value='';
    };xhr.send(file);
   };
  }
 }catch{status.textContent='The service is unavailable. Reload after checking the deployment.';}
})();
