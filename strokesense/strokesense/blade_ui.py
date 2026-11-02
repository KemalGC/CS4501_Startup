"""Explicit, separate model-only blade selection on the private library server."""
from __future__ import annotations
import base64
import hmac
import html
import math
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from . import web
from .blade_video import reference_frame
from .registry import _stream_sha256, list_clips
from .selection import validate_selection

_ID = re.compile(r'[0-9a-f]{64}\Z')


def add_blade_routes(server, jobs, registry):
    base = server.RequestHandlerClass
    def source_for(cid):
        if not _ID.fullmatch(cid): raise ValueError('invalid_clip')
        clip = next((c for c in list_clips(registry, show_paths=True) if c['clip_id'] == cid), None)
        if clip is None: raise LookupError('clip_missing')
        if clip['permission'] != 'granted': raise PermissionError('permission_required')
        source = Path(clip['source_path'])
        if source.stat().st_size > web._MAX_VIDEO_BYTES or _stream_sha256(source) != clip['sha256']:
            raise ValueError('source_changed')
        return source

    class BladeHandler(base):
        def _send(self, code, data, **kwargs):
            location = kwargs.get('location')
            if os.environ.get('STROKESENSE_BLADE_MODEL') and isinstance(location, str):
                for route in ('/select?clip=', '/review?clip='):
                    if location.startswith(route):
                        kwargs['location'] = location.replace(route, '/blade?clip=', 1)
                        break
            return super()._send(code, data, **kwargs)

        def problem(self, code):
            text = {403: 'Permission or request validation failed. No model analysis started.',
                    404: 'This saved recording is unavailable.',
                    422: 'Choose a visible blade on a valid reference frame and confirm its boat.',
                    503: 'Configure an installed local vision model first: start the library with --blade-model MODEL. '
                         'Run Ollama locally; no model will be downloaded by this page.'}.get(code,
                         'The saved recording changed or could not be decoded. Return to the library.')
            self._send(code, web._document('Blade model unavailable', '<p role="alert">' + text +
                       '</p><p><a href="/library">Back to library</a></p>'))

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path not in ('/blade', '/blade.js'): return super().do_GET()
            if not self._trusted_request(): self.problem(403); return
            if parsed.path == '/blade.js':
                if parsed.query: self.problem(422); return
                self._send(200, BLADE_JS.encode(), mime='application/javascript; charset=utf-8'); return
            try:
                if len(parsed.query) > 110: raise ValueError('invalid_query')
                q = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True, max_num_fields=2)
                if set(q) - {'clip', 'seconds'} or 'clip' not in q or any(len(v) != 1 for v in q.values()):
                    raise ValueError('invalid_query')
                cid = q['clip'][0]; source = source_for(cid)
                seconds = float(q.get('seconds', ['0'])[0])
                if not math.isfinite(seconds) or not 0 <= seconds <= 600: raise ValueError('invalid_time')
                image, actual = reference_frame(source, seconds)
                source_for(cid)  # Recheck permission/hash after decoding.
                model = os.environ.get('STROKESENSE_BLADE_MODEL', '').strip()
                configured = bool(model)
                body = ('<p><strong>Experimental model-only blade rate.</strong> Select ONE visible blade belonging '
                    'to your boat. The local vision model follows that blade and classifies water contact. '
                    'It does not run the old body-curve stroke detector or technique scoring rules.</p>'
                    '<p>Generic vision-model accuracy on rowing contact is not validated. Check every reported entry. '
                    'Occlusion and uncertain identity become unknown, not guessed strokes.</p>'
                    f'<form method="get" action="/blade"><input type="hidden" name="clip" value="{cid}">'
                    '<label>Reference time (seconds) <input name="seconds" type="number" min="0" max="600" step="0.1" '
                    f'value="{seconds:g}"></label><button>Show this frame</button></form>'
                    f'<p>Decoded reference: {actual:.3f} source seconds. Click the blade, not the handle or rower. '
                    'Keyboard: focus the image and use arrow keys, or enter normalized X/Y below.</p>'
                    '<canvas id="blade-canvas" tabindex="0" style="width:100%;height:auto;border:2px solid #087f70" '
                    'aria-label="Choose one reference blade with a click or arrow keys"></canvas>'
                    f'<img id="blade-image" hidden alt="Reference recording frame" src="data:image/jpeg;base64,{base64.b64encode(image).decode()}">'
                    '<form method="post" action="/blade" id="blade-form">'
                    f'<input type="hidden" name="clip" value="{cid}">'
                    f'<input type="hidden" name="csrf" value="{html.escape(server.csrf_token, quote=True)}">'
                    f'<input type="hidden" name="seconds" value="{actual:.8f}">'
                    '<label>Blade X (0–1) <input name="x" type="number" min="0.001" max="0.999" step="0.001" required></label>'
                    '<label>Blade Y (0–1) <input name="y" type="number" min="0.001" max="0.999" step="0.001" required></label>'
                    '<label><input type="checkbox" name="confirm" value="yes" required> '
                    'This is one blade from the boat I want analyzed.</label>'
                    f'<button type="submit" {"disabled" if not configured else ""}>Analyze blade entries</button></form>'
                    '<p id="blade-status" role="status">No blade selected.</p>'
                    + (f'<p>Local model: <code>{html.escape(model)}</code>. Samples up to 20 seconds near this reference.</p>'
                       if configured else '<p role="alert">No local vision model configured. Start the library with '
                       '<code>--blade-model MODEL</code> after installing that model in Ollama. Nothing is downloaded here.</p>')
                    + '<p>Two clear entries of the same blade are enough for a provisional rate. Quick mode stops after one supported interval; model accuracy remains unvalidated. '
                    'Technique grades remain withheld in this mode.</p><p><a href="/library">Back to library</a></p>'
                    '<script src="/blade.js" defer></script>')
                self._send(200, web._document('Model-only blade rate', body),
                    csp=web._PAGE_CSP + "; img-src data:; script-src 'self'")
            except PermissionError: self.problem(403)
            except LookupError: self.problem(404)
            except (ValueError, OSError): self.problem(409)
            except Exception: self.problem(503)

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path != '/blade': return super().do_POST()
            if not self._trusted_request(): self.problem(403); return
            try:
                lengths = self.headers.get_all('Content-Length') or []
                if (parsed.query or len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,4}', lengths[0])
                        or self.headers.get_all('Transfer-Encoding')
                        or self.headers.get_content_type() != 'application/x-www-form-urlencoded'):
                    raise ValueError('invalid_request')
                size = int(lengths[0])
                if not 0 < size <= 2048: raise ValueError('invalid_size')
                self.connection.settimeout(5); raw = self.rfile.read(size)
                if len(raw) != size: raise ValueError('incomplete_body')
                f = parse_qs(raw.decode(), strict_parsing=True, keep_blank_values=True, max_num_fields=6)
                if set(f) != {'clip', 'csrf', 'seconds', 'x', 'y', 'confirm'} or any(len(v) != 1 for v in f.values()):
                    raise ValueError('invalid_form')
                f = {k: v[0] for k, v in f.items()}
                if not hmac.compare_digest(f['csrf'].encode(), server.csrf_token.encode()):
                    self.problem(403); return
                selected = validate_selection({'version': 3, 'kind': 'blade_reference',
                    'reference_seconds': float(f['seconds']), 'point': [float(f['x']), float(f['y'])],
                    'confirmed_same_boat': f['confirm'] == 'yes'})
                source = source_for(f['clip'])
                # Validate the requested reference before creating a job.
                reference_frame(source, selected['reference_seconds'])
                if not os.environ.get('STROKESENSE_BLADE_MODEL', '').strip():
                    self.problem(503); return
                job = jobs.submit(f['clip'], selection=selected)
                self._send(303, b'', location='/jobs/' + job['job_id'])
            except PermissionError: self.problem(403)
            except LookupError: self.problem(404)
            except (ValueError, OSError, TimeoutError): self.problem(422)
            except Exception: self.problem(503)
    server.RequestHandlerClass = BladeHandler
    return server


BLADE_JS = r"""'use strict';
(() => {
 const image = document.getElementById('blade-image'), canvas = document.getElementById('blade-canvas');
 const form = document.getElementById('blade-form'), ctx = canvas.getContext('2d');
 const x = form.elements.namedItem('x'), y = form.elements.namedItem('y');
 function draw() {
  if (!image.complete || !image.naturalWidth) return;
  canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
  ctx.drawImage(image, 0, 0);
  if (x.value && y.value) {ctx.beginPath();ctx.strokeStyle='#b22d1c';ctx.lineWidth=3;
   ctx.arc(Number(x.value)*canvas.width,Number(y.value)*canvas.height,18,0,2*Math.PI);ctx.stroke();}
 }
 function changed(){form.elements.namedItem('confirm').checked=false;
  document.getElementById('blade-status').textContent='Reference blade: '+x.value+', '+y.value+'. Confirm the boat below.';draw();}
 canvas.addEventListener('click', event => {const r=canvas.getBoundingClientRect();
  x.value=Math.max(.001,Math.min(.999,(event.clientX-r.left)/r.width)).toFixed(3);
  y.value=Math.max(.001,Math.min(.999,(event.clientY-r.top)/r.height)).toFixed(3);changed();});
 canvas.addEventListener('keydown', event => {const delta={ArrowLeft:[-.005,0],ArrowRight:[.005,0],ArrowUp:[0,-.005],ArrowDown:[0,.005]}[event.key];
  if(!delta)return;event.preventDefault();
  x.value=Math.max(.001,Math.min(.999,(Number(x.value)||.5)+delta[0])).toFixed(3);
  y.value=Math.max(.001,Math.min(.999,(Number(y.value)||.5)+delta[1])).toFixed(3);changed();});
 x.addEventListener('input',changed); y.addEventListener('input',changed);
 image.addEventListener('load',draw);draw();
})();
"""
