"""Local selection preview and self-hosted interaction; never invokes a model."""
from __future__ import annotations
import base64
import html
from pathlib import Path


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
        if w > 1280:
            frame = cv2.resize(frame, (1280, round(h * 1280 / w)))
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok or len(buf) > 2 * 1024 * 1024:
            raise ValueError('preview_unavailable')
        return 'data:image/jpeg;base64,' + base64.b64encode(buf).decode('ascii')
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
        '<p>Use a clip with all eight rowers visible in the first frame. Click the top-left and '
        'bottom-right corners of a region containing <strong>only your boat</strong>, then click '
        'inside each of its eight rowers, in a consistent order. Do not select the coxswain.</p>'
        '<p>The region stays fixed for this clip. Keep the boat inside it; use a shorter clip '
        'if another boat crosses it or rowers become hidden. Membership is your confirmation, '
        'not automatic boat recognition. Ambiguous or lost tracking stops the analysis.</p>'
        '<form method="post" action="/select" id="crew-selection">'
        '<input type="hidden" name="csrf" value="' + html.escape(token, quote=True) + '">'
        '<input type="hidden" name="clip_id" value="' + html.escape(clip_id, quote=True) + '">'
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
  function field(name) { return form.elements.namedItem(name); }
  function set(name, value) { field(name).value = (value * 100).toFixed(3); }
  function draw() {
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
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
  function ready() { canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;draw(); }
  if (image.complete) ready(); else image.addEventListener('load',ready);
  canvas.addEventListener('click', event => {
    if (points.length >= 10) return;
    const rect=canvas.getBoundingClientRect();
    const p=[Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),
             Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
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
  form.addEventListener('input',draw);
  document.getElementById('selection-reset').addEventListener('click',()=>{
    points=[];form.reset();
    form.querySelectorAll('input[type=number]').forEach(el=>el.value='');
    status.textContent='Click the top-left corner of your boat region.';draw();
  });
})();
"""
