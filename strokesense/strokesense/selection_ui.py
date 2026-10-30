"""Private first-frame preview, automatic people proposals and manual fallback."""
from __future__ import annotations
import base64
import html
from . import auto_selection


def preview_jpeg(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('preview_unavailable')
        ok, frame = cap.read()
        if not ok or frame is None or frame.ndim != 3:
            raise ValueError('preview_unavailable')
        h, w = frame.shape[:2]
        if h < 64 or w < 64 or w * h > 3840 * 2160:
            raise ValueError('preview_unavailable')
        proposals = auto_selection.suggest(frame)
        if w > 1280:
            frame = cv2.resize(frame, (1280, round(h * 1280 / w)))
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok or len(buf) > 2 * 1024 * 1024:
            raise ValueError('preview_unavailable')
        return auto_selection.Preview('data:image/jpeg;base64,' + base64.b64encode(buf).decode('ascii'), proposals)
    finally:
        cap.release()


def selection_form(clip_id, token, image):
    def number(name, label):
        return (f'<label>{label}<input type="number" name="{name}" min="0" max="100" '
                'step="0.001" required></label>')
    region = ''.join(number(name, label) for name, label in
                     [('left', 'Left'), ('top', 'Top'), ('right', 'Right'), ('bottom', 'Bottom')])
    people = ''.join('<fieldset><legend>Selected ' + str(i+1) + '</legend>'
                     + number('x'+str(i), 'Horizontal (%)') + number('y'+str(i), 'Vertical (%)')
                     + '</fieldset>' for i in range(8))
    return (
        '<section aria-labelledby="choose-crew"><h2 id="choose-crew">Choose eight rowers from one boat</h2>'
        '<p>Use a clip with all eight rowers visible in the first frame. When detections are '
        'available, select the numbered people below. Do not select the coxswain.</p>'
        '<p>For manual selection, mark the top-left and bottom-right corners around '
        '<strong>only your boat</strong>, then click its eight rowers in a consistent order.</p>'
        '<p>A manually selected region stays fixed for this clip. Keep the boat inside it; use a shorter clip '
        'if another boat crosses it or rowers become hidden. Membership is your confirmation, '
        'not automatic boat recognition. Ambiguous or lost tracking stops the analysis.</p>'
        '<form method="post" action="/select" id="crew-selection">'
        '<input type="hidden" name="csrf" value="' + html.escape(token, quote=True) + '">'
        '<input type="hidden" name="clip_id" value="' + html.escape(clip_id, quote=True) + '">'
        + auto_selection.controls(image) +
        '<div style="width:100%"><img id="crew-preview" src="' + image + '" '
        'alt="First video frame. Use the selection canvas or enter coordinates below." '
        'style="display:none">'
        '<canvas id="crew-canvas" style="width:100%;height:auto;touch-action:manipulation;'
        'border:2px solid #087f70" aria-label="Boat and rower selection preview"></canvas></div>'
        '<noscript><p>JavaScript is unavailable. Use the coordinate fields below.</p>'
        '<img src="' + image + '" alt="First video frame" style="max-width:100%"></noscript>'
        '<p id="selection-progress" role="status" aria-live="polite">Click the top-left corner of your boat region.</p>'
        '<button type="button" id="selection-reset">Reset selection</button>'
        '<details style="width:100%"><summary>Keyboard / numeric coordinates (percent of image)</summary>'
        '<fieldset><legend>Boat region</legend>' + region + '</fieldset>' + people + '</details>'
        '<label><input type="checkbox" name="same_boat" value="yes" required> '
        'I confirm these eight rowers are all in the same boat.</label>'
        '<button type="submit">Analyze selected crew</button></form>'
        '<p><a href="/">Back to library</a>. Full-frame automatic analysis is still available there; '
        'it does not guarantee one-boat membership.</p></section>'
        '<script src="/selection.js" defer></script>'
    )


SELECTION_JS = r"""'use strict';
(() => {
  const form = document.getElementById('crew-selection');
  const image = document.getElementById('crew-preview');
  const canvas = document.getElementById('crew-canvas');
  const status = document.getElementById('selection-progress');
  const ctx = canvas.getContext('2d');
  let points = [];
  const panel = document.getElementById('detected-people');
  const candidates = panel ? JSON.parse(panel.dataset.candidates) : [];
  let automatic = candidates.length > 0;
  let selected = [];
  function clearFields() {
    points=[];selected=[];
    form.querySelectorAll('input[type=number]').forEach(el=>el.value='');
    field('same_boat').checked=false;
    form.querySelectorAll('.person-toggle').forEach(el=>el.checked=false);
  }
  function applyCandidates() {
    form.querySelectorAll('input[type=number]').forEach(el=>el.value='');
    ['left','top','right','bottom'].forEach((name,i)=>set(name,i<2?0:1));
    selected.forEach((index,i)=>{
      set('x'+i,candidates[index].seed[0]);set('y'+i,candidates[index].seed[1]);
    });
    form.querySelectorAll('.person-toggle').forEach(el=>el.checked=selected.includes(Number(el.dataset.person)));
    field('same_boat').checked=false;
    form.querySelector('button[type=submit]').disabled=selected.length!==8;
    document.getElementById('candidate-count').textContent=selected.length+' of 8 selected.';
    status.textContent=selected.length+' of 8 selected.'+(selected.length===8 ?
      ' Confirm these rowers belong to the same boat, then analyze.' :
      ' Select only your boat’s rowers, not the coxswain.');
    draw();
  }
  function toggleCandidate(index) {
    if (!automatic || !candidates[index].seed) return;
    if (selected.includes(index)) selected=selected.filter(i=>i!==index);
    else if(selected.length<8) selected.push(index);
    else {
      status.textContent='Eight already selected. Deselect someone before adding another person.';
      form.querySelectorAll('.person-toggle').forEach(el=>el.checked=selected.includes(Number(el.dataset.person)));
      return;
    }
    applyCandidates();
  }
  if(panel) {
    panel.querySelectorAll('.person-toggle').forEach(el=>el.addEventListener('change',()=>toggleCandidate(Number(el.dataset.person))));
    document.getElementById('selection-manual').addEventListener('click',()=>{
      automatic=false;clearFields();panel.hidden=true;
      form.querySelector('button[type=submit]').disabled=false;
      status.textContent='Click the top-left corner of your boat region.';draw();
    });
    document.getElementById('selection-auto').addEventListener('click',()=>{
      automatic=true;clearFields();panel.hidden=false;applyCandidates();
    });
  }
  form.addEventListener('submit',event=>{
    if(automatic && selected.length!==8) {
      event.preventDefault();status.textContent='Select exactly eight detected people from one boat.';
    }
  });
  function field(name) { return form.elements.namedItem(name); }
  function set(name, value) { field(name).value = (value * 100).toFixed(3); }
  function draw() {
    if (!image.complete || !image.naturalWidth) return;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    if(automatic) candidates.forEach((candidate,index)=>{
      const [l,t,r,b]=candidate.box;
      const chosen=selected.includes(index);
      ctx.strokeStyle=chosen?'#0b735f':'#185acb';ctx.lineWidth=chosen?4:2;
      ctx.setLineDash(chosen?[]:[6,3]);
      ctx.strokeRect(l*canvas.width,t*canvas.height,(r-l)*canvas.width,(b-t)*canvas.height);
      ctx.setLineDash([]);ctx.fillStyle=chosen?'#0b735f':'#123454';
      ctx.fillRect(l*canvas.width,t*canvas.height,65,23);
      ctx.fillStyle='#ffffff';ctx.font='bold 14px sans-serif';ctx.textAlign='left';ctx.textBaseline='top';
      ctx.fillText('Person '+candidate.id,l*canvas.width+3,t*canvas.height+3);
    });
    const values = ['left','top','right','bottom'].map(n => field(n).value);
    if (values.every(v => v !== '')) {
      const [l,t,r,b] = values.map(v => Number(v)/100);
      ctx.strokeStyle = '#00ffe1'; ctx.lineWidth = 3;
      ctx.strokeRect(l*canvas.width,t*canvas.height,(r-l)*canvas.width,(b-t)*canvas.height);
    }
    for (let i=0; i<8; i++) {
      if (field('x'+i).value === '' || field('y'+i).value === '') continue;
      const x = Number(field('x'+i).value)*canvas.width/100;
      const y = Number(field('y'+i).value)*canvas.height/100;
      ctx.beginPath(); ctx.arc(x,y,12,0,Math.PI*2); ctx.fillStyle='#ffffff'; ctx.fill();
      ctx.strokeStyle='#12263b'; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle='#12263b';
      ctx.font='bold 16px sans-serif'; ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillText(String(i+1),x,y);
    }
  }
  function ready() { canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;if(automatic) applyCandidates();else draw(); }
  if (image.complete) ready(); else image.addEventListener('load',ready);
  canvas.addEventListener('click', event => {
    if (!automatic && points.length >= 10) return;
    const rect=canvas.getBoundingClientRect();
    const p=[Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),
             Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
    if(automatic) {
      const hits=candidates.map((c,i)=>({c,i})).filter(({c})=>p[0]>=c.box[0]&&p[0]<=c.box[2]&&p[1]>=c.box[1]&&p[1]<=c.box[3]);
      if(hits.length===1) toggleCandidate(hits[0].i);
      else status.textContent='Use the labeled toggles to select overlapping detections.';
      return;
    }
    if (points.length >= 2) {
      const [l,t,r,b]=['left','top','right','bottom'].map(n=>Number(field(n).value)/100);
      if (!(p[0]>l && p[0]<r && p[1]>t && p[1]<b)) {
        status.textContent='Select a rower inside the chosen boat region.';return;
      }
    }
    points.push(p);
    if (points.length === 1) status.textContent='Click the bottom-right corner of the same boat region.';
    else if (points.length === 2) {
      set('left',Math.min(points[0][0],p[0]));set('top',Math.min(points[0][1],p[1]));
      set('right',Math.max(points[0][0],p[0]));set('bottom',Math.max(points[0][1],p[1]));
      status.textContent='Select rower 1 of 8 from this boat.';
    } else {
      const i=points.length-3;set('x'+i,p[0]);set('y'+i,p[1]);
      status.textContent=points.length===10 ? '8 of 8 selected. Confirm one-boat membership below.' :
        'Select rower '+(i+2)+' of 8 from this boat.';
    }
    draw();
  });
  form.addEventListener('input',event=>{
    if(automatic && event.target.type==='number') {
      automatic=false;selected=[];if(panel) panel.hidden=true;
      form.querySelector('button[type=submit]').disabled=false;
      field('same_boat').checked=false;
      status.textContent='Manual coordinates active. Confirm the final eight rowers.';
    }
    draw();
  });
  document.getElementById('selection-reset').addEventListener('click',()=>{
    clearFields();
    if(automatic) {applyCandidates();return;}
    status.textContent='Click the top-left corner of your boat region.';draw();
  });
})();
"""
