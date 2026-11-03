'use strict';
/* Library metadata only. Every private asset still requires the review session. */
(() => {
 const $ = id => document.getElementById(id);
 let study = null;
 function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
 }
 function link(text, href, cls) {const a=node('a',text,cls);a.href=href;return a;}
 function render() {
  const root=$('report-cards');root.replaceChildren();
  if (!study?.session) return;
  const query=$('report-search').value.trim().toLowerCase();
  const clips=study.clips.filter(c=>c.title.toLowerCase().includes(query));
  const counts={analysis:0,diagnostic:0,unavailable:0};
  study.clips.forEach(c=>counts[c.report_state || 'unavailable']++);
  $('reports-count').textContent=`${study.clips.length} recordings · ${counts.analysis} reports · ${counts.diagnostic} diagnostics · ${counts.unavailable} unavailable`;
  const groups={};study.clips.forEach(c=>{if(c.group_id)groups[c.group_id]=(groups[c.group_id]||0)+1;});
  clips.forEach(c=>{
   const card=node('article',undefined,'report-card panel');card.dataset.clip=c.id;
   if(c.assets.includes('poster')){const img=node('img');img.src='/asset/'+encodeURIComponent(c.id)+'/poster';img.alt='Recording preview: '+c.title;img.loading='lazy';card.append(img);}
   const body=node('div',undefined,'report-card-body');
   const available=c.assets.includes('report');
   const kind=available?(c.report_state==='analysis'?'Provisional analysis':'Detection diagnostic'):'Report unavailable';
   body.append(node('span',kind,'badge'+(c.report_state==='analysis'?'':' warning')),node('h3',c.title));
   const window=c.analysis.window;
   body.append(node('p',window?`Analyzed source: ${window.start.toFixed(1)}–${window.end.toFixed(1)} s`:'No analyzed window recorded.','muted'));
   if(c.group_id&&groups[c.group_id]>1)body.append(node('p','Paired upload · same recording group','paired-note'));
   if(!available)body.append(node('p','No saved report is available for this recording. You can still watch the source and review its limitation messages.','report-limit'));
   const actions=node('div',undefined,'report-actions');
   if(available)actions.append(link(c.report_state==='analysis'?'Open report':'Open diagnostic','/library?clip='+encodeURIComponent(c.id)+'&report=1','primary'));
   actions.append(link('Review video','/?clip='+encodeURIComponent(c.id),'secondary'));
   body.append(actions);card.append(body);root.append(card);
  });
  $('report-empty').hidden=clips.length!==0;
 }
 window.addEventListener('ss:ready',event=>{
  study=event.detail;
  const params=new URLSearchParams(location.search);
  const selected=study.clips.some(c=>c.id===params.get('clip'));
  const library=location.pathname==='/library'&&!selected;
  $('reports-library').hidden=!study.session||!library;
  $('reports-nav').setAttribute('aria-current',library?'page':'false');
  if(study.session){$('workspace').hidden=library;render();}
  else{$('report-cards').replaceChildren();$('report-frame').removeAttribute('src');$('video').pause();}
  if(study.session&&selected&&params.get('report')==='1'){
   window.dispatchEvent(new Event('ss:open-report'));
   $('report-panel').scrollIntoView({block:'start',behavior:'auto'});
  }
 });
 $('report-search').addEventListener('input',render);
})();
