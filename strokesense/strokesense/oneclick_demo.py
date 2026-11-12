"""Private one-click REAL inference demo for a prepared eights clip.

Run from the repository's strokesense/ directory:
    python -m strokesense.oneclick_demo --video /path/to/IMG_5092_eights_16s.mp4

This is intentionally local-only. It starts a fresh CPU model subprocess on click;
it does not read or mutate the seven-clip reviewer study, its DB, or responses.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

MAX_DURATION_SECONDS = 30 * 60
MAX_MEDIA_BYTES = 150 * 1024 * 1024
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_METRICS_BYTES = 16 * 1024 * 1024

def summarize_crew_metrics(metrics):
    """Expose only actual saved model measurements, never assume 8 identities.

    A track count is not independent identity verification; a missing cadence
    stays unavailable instead of being silently substituted from one rower.
    """
    if not isinstance(metrics, dict) or not isinstance(metrics.get('rowers'), list):
        raise ValueError('invalid_crew_metrics')
    rowers = metrics['rowers']
    if not 2 <= len(rowers) <= 9:
        raise ValueError('no_usable_crew_tracks')
    seen, strokes = set(), 0
    for rower in rowers:
        if not isinstance(rower, dict):
            raise ValueError('invalid_crew_rower')
        seat, cycles = rower.get('seat'), rower.get('strokes')
        if (not isinstance(seat, str) or not 1 <= len(seat) <= 80 or seat in seen
                or not isinstance(cycles, list) or len(cycles) > 10000
                or not all(isinstance(cycle, dict) for cycle in cycles)):
            raise ValueError('invalid_crew_rower')
        seen.add(seat)
        strokes += len(cycles)
    if strokes < 1:
        raise ValueError('no_usable_strokes')
    cadence = metrics.get('crew_cadence')
    if not isinstance(cadence, dict):
        raise ValueError('invalid_crew_cadence')
    rate = cadence.get('rate_spm')
    if rate is not None and (type(rate) not in (int, float) or not math.isfinite(rate)
                             or not 5 <= rate <= 90):
        raise ValueError('invalid_crew_cadence')
    return {'candidate_rowers': len(rowers), 'observed_cycles': strokes,
            'shared_rate_spm': round(float(rate), 1) if rate is not None else None,
            'full_eight_observed': len(rowers) == 8,
            'method': 'model candidate tracks; not independently verified rower identities'}


def _safe_result(base: Path, path: Path) -> bool:
    """No symlinks or unexpected output paths are ever served from /result."""
    root = base.resolve(strict=True)
    resolved = path.resolve(strict=True)
    return resolved.is_relative_to(root) and path.is_file() and not path.is_symlink()


def _safe_media(path, raw_range, *, head=False, writer=None, mime="video/mp4"):
    """RFC 7233 single-range serving, without exposing arbitrary filesystem paths."""
    n = path.stat().st_size
    if n < 1:
        return (416, 0, 0, {"Content-Range": "bytes */0"})
    first, last, status = 0, n - 1, 200
    if raw_range is not None:
        # Bound decimal parsing before converting attacker-controlled ranges.
        if len(raw_range) > 64:
            return (416, 0, 0, {"Content-Range": f"bytes */{n}"})
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw_range)
        if match is None or not any(match.groups()):
            return (416, 0, 0, {"Content-Range": f"bytes */{n}"})
        a, b = match.groups()
        if a:
            first = int(a)
            if b:
                last = min(last, int(b))
        else:
            size = int(b)
            if size < 1:
                return (416, 0, 0, {"Content-Range": f"bytes */{n}"})
            first = max(0, n - size)
        if first >= n or first > last:
            return (416, 0, 0, {"Content-Range": f"bytes */{n}"})
        status = 206
    extra = {"Accept-Ranges": "bytes", "Content-Type": mime,
             "Content-Length": str(last - first + 1)}
    if status == 206:
        extra["Content-Range"] = f"bytes {first}-{last}/{n}"
    if writer is not None and not head:
        with path.open("rb") as stream:
            stream.seek(first)
            remaining = last - first + 1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                writer.write(chunk)
                remaining -= len(chunk)
    return status, first, last, extra


PAGE = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>StrokeSense | One-click eights demo</title>
<style nonce="__NONCE__">
:root{color-scheme:light;--ink:#102c35;--muted:#4e636a;--mint:#d9eee9;--accent:#0e776a}
*{box-sizing:border-box}body{margin:0;background:#f3f7f6;font:16px/1.5 system-ui,Segoe UI,sans-serif;color:var(--ink)}
header{background:#0c2632;color:white;padding:17px max(18px,calc((100vw - 1000px)/2));font-weight:700;letter-spacing:.02em}
small,.meta{font-size:15px;color:var(--muted)}main{max-width:1030px;margin:30px auto;padding:0 20px 30px}
.hero{display:flex;justify-content:space-between;align-items:start;gap:24px}.tag{font-size:15px;color:var(--accent);font-weight:800;text-transform:uppercase}
h1{font-size:clamp(29px,4vw,43px);line-height:1.13;margin:9px 0 13px;max-width:690px}
.lede{font-size:18px;color:#41545c;margin:0 0 24px;max-width:750px}
.grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(330px,1fr);gap:22px}
.card{background:white;border:1px solid #d3e2de;border-radius:17px;padding:23px;box-shadow:0 4px 20px rgba(16,44,53,.05)}
video{width:100%;aspect-ratio:16/9;background:#101b21;border-radius:10px;display:block}
.btn{cursor:pointer;border:0;border-radius:12px;background:#0e776a;color:white;font:700 19px/1.2 system-ui;padding:17px 21px;width:100%}
.btn:disabled{cursor:not-allowed;background:#788d8a}
.secondary{display:block;text-align:center;text-decoration:none;border-radius:10px;border:1px solid #537e76;color:#125448;padding:12px 8px;font-weight:700;margin-top:12px}
h2{font-size:24px;margin:0 0 11px}p{margin:9px 0} .status{font-size:18px;font-weight:700;margin-top:16px}
.progress{height:12px;border-radius:100px;background:#dce7e5;overflow:hidden;margin-top:12px}.bar{height:100%;background:#22a998;width:0;transition:width .25s}
.links a{display:block}.note{border-left:4px solid #e4ad5b;background:#fffaed;padding:12px 13px;border-radius:6px;margin-top:18px}
#details{white-space:pre-wrap;overflow-wrap:anywhere;color:#526168;line-height:1.4;font-size:15px}
[hidden]{display:none!important}footer{max-width:1030px;margin:8px auto 30px;padding:0 20px;color:#486268;font-size:15px}
@media(max-width:760px){.grid{grid-template-columns:1fr}.hero{display:block}.card{padding:18px}}
</style></head><body>
<header>≋ StrokeSense <span style="font-weight:400;opacity:.75">&nbsp; / &nbsp; Local eights demonstration</span></header>
<main><div class="hero"><div><div class="tag">Real model analysis • Prepared video</div><h1>Watch the eight. Then analyze the stroke.</h1>
<p class="lede">The 16-second eights clip is ready to play. Click <b>Analyze now</b> to run fresh pose detection, crew rhythm estimation, and a source-linked report.</p></div></div>
<div class="grid"><section class="card" aria-labelledby="video-title"><h2 id="video-title">IMG_5092 · 16-second eights clip</h2>
<video controls playsinline preload="metadata" src="/video" aria-label="Prepared eights video"></video>
<p class="meta">Original window: 10–26 seconds of IMG_5092.MOV. The report will be computed on this exact 16-second excerpt.</p>
<div id="crew-summary" class="note" role="status" aria-live="polite" hidden></div>
<div id="result-links" class="links" hidden><a class="secondary" href="/report" target="_blank" rel="noopener">Open generated analysis report</a>
<a id="annotated" class="secondary" href="/annotated" target="_blank" rel="noopener">Watch generated model overlay</a></div></section>
<section class="card" aria-labelledby="run-title"><h2 id="run-title">Run the model</h2>
<p>Click once to start actual inference on this clip. The button does not replay a precomputed result.</p>
<button id="analyze" class="btn" type="button">Analyze now</button>
<p id="state" class="status" role="status" aria-live="polite">Ready for analysis</p>
<div class="progress" aria-hidden="true"><div id="bar" class="bar"></div></div>
<p id="details">Once it starts, the status updates as the model works through the video and builds its report.</p>
<div class="note">Runs on your own computer. CPU pose estimation can take several minutes. When a model or codec dependency is missing, you will see a clear failure rather than an invented score. Saved reviewer-study responses are untouched.</div>
</section></div></main><footer>No model output is treated as a coach-validated assessment. The demo is available only on this computer.</footer>
<script nonce="__NONCE__">
const token = __CSRF_JSON__;
const button = document.getElementById('analyze');
const status = document.getElementById('state');
const details = document.getElementById('details');
const bar = document.getElementById('bar');
const links = document.getElementById('result-links');
const overlay = document.getElementById('annotated');
const crew = document.getElementById('crew-summary');
async function refresh(){
 try{
  const response=await fetch('/api/status',{cache:'no-store',credentials:'same-origin'});
  if(!response.ok)throw Error('Status request failed');
  const data=await response.json();
  status.textContent=data.label;
  details.textContent=data.detail;
  button.disabled=data.state==='running'||data.state==='finished';
  button.textContent=data.state==='running'?'Analyzing video…':data.state==='finished'?'Analysis finished':'Analyze now';
  bar.style.width=(data.progress||0)+'%';
  links.hidden=data.state!=='finished';
  overlay.hidden=!data.has_overlay;
  crew.hidden=data.state!=='finished'||!data.crew_summary;
  if(!crew.hidden){const info=data.crew_summary;const rate=info.shared_rate_spm===null?'rate unavailable':info.shared_rate_spm.toFixed(1)+' shared boat SPM';crew.textContent=info.candidate_rowers+' candidate rower tracks · '+info.observed_cycles+' measured stroke cycles · '+rate+'. '+(info.full_eight_observed?'Tracks are not independently identity-verified.':'Not all eight rowers were identified; review the report before drawing conclusions.');}
 }catch(e){status.textContent='Unable to connect to the local analysis service';details.textContent='Check the terminal running the demo.'}
}
button.addEventListener('click',async()=>{
 button.disabled=true;status.textContent='Starting the analysis…';
 try{
  const r=await fetch('/api/analyze',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json','x-csrf-token':token},body:'{}'});
  const data=await r.json();if(!r.ok)throw Error(data.error||'Could not start');
 }catch(e){status.textContent='Could not start';details.textContent=e.message;button.disabled=false;}
 await refresh();
});
refresh();setInterval(refresh,1200);
</script></body></html>'''


class DemoState:
    """One CPU inference at a time; no study database or participant input."""
    def __init__(self, video, out_dir, *, command_factory=None):
        self.video = Path(video).expanduser().resolve(strict=True)
        if not self.video.is_file() or self.video.suffix.lower() not in {'.mp4', '.mov', '.webm'}:
            raise ValueError('a_prepared_video_file_is_required')
        if not 0 < self.video.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError('unsupported_prepared_video_size')
        self.root = Path(out_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.command_factory = command_factory or self._command
        self.lock = threading.Lock()
        self.phase = 'ready'
        self.error = ''
        self.last_start = None
        self.last_end = None
        self.report = None
        self.overlay = None
        self.crew_summary = None
        self.log = None
        self.worker = None
        self.cancel_requested = threading.Event()
        self.process = None

    def _command(self):
        return [sys.executable, '-u', '-m', 'strokesense.cli', str(self.video),
                '--out', str(self.root), '--fps', '10', '--dominant-crew', '--threads','2']

    def _stop_process(self, proc):
        """Stop this analysis subprocess and its descendants without blocking the HTTP handler."""
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == 'posix':
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except (OSError, ProcessLookupError):
            return

        def force_stop():
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                if proc.poll() is None:
                    try:
                        if os.name == 'posix':
                            os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.kill()
                    except (OSError, ProcessLookupError):
                        pass
        threading.Thread(target=force_stop, daemon=True).start()

    def cancel(self):
        """Request cancellation of a running worker; preserve uploaded inputs and prior files."""
        with self.lock:
            if self.phase != 'running' and not (self.worker and self.worker.is_alive()):
                return False
            self.cancel_requested.set()
            proc = self.process
        self._stop_process(proc)
        return True

    def snapshot(self):
        with self.lock:
            phase = self.phase
            error = self.error
            report = self.report
            overlay = self.overlay
            crew_summary = self.crew_summary
            log = self.log
            start = self.last_start
        label = {'ready': 'Ready for analysis', 'running': 'Running StrokeSense',
                 'finished': 'Analysis finished', 'failed': 'Analysis could not finish'}[phase]
        progress = {'ready':0,'running':5,'finished':100,'failed':0}[phase]
        detail = {'ready':'The prepared eights clip is loaded. Press Analyze now to begin.',
                  'running':'Preparing pose tracking and stroke measurements…',
                  'finished':'Open the generated report to review the measurements and their limitations.',
                  'failed':'The real analysis did not complete. Check the local environment and try again.'}[phase]
        if phase == 'running' and log and log.exists():
            try:
                with log.open('rb') as inp:
                    inp.seek(max(0,inp.seek(0,os.SEEK_END)-8192))
                    data = inp.read(8192).decode('utf-8','replace')
                # Only expose bounded, non-private progress tokens.
                found = re.findall(r'frame\s+(\d+)/(\d+)', data)
                if found:
                    a,b = map(int,found[-1])
                    if b > 0:
                        detail=f'Pose frames processed: {a} / {b}. The report is generated after pose tracking.'
                        progress=max(6,min(82,int(6+76*a/b)))
                elif '[4/4]' in data:progress=95;detail='Building the source-linked report…'
                elif '[3/4]' in data:progress=89;detail='Rendering the model-overlay video…'
                elif '[2/4]' in data:progress=85;detail='Estimating rowing strokes and crew rhythm…'
            except OSError:
                pass
        if phase=='failed':
            detail={'model_missing':'The pose model could not be loaded. Install requirements and retry.',
                    'analysis_timeout':'The CPU analysis exceeded its time limit.',
                    'no_usable_strokes':'The model could not produce a reliable report for this view.',
                    'analysis_failed':'The model process failed. See the private terminal for diagnostic details.',
                    'invalid_crew_metrics':'The report did not contain usable measured crew data.',
                    'invalid_crew_rower':'The crew track data could not be validated.',
                    'invalid_crew_cadence':'The saved shared boat cadence was invalid.',
                    'no_usable_crew_tracks':'The model did not identify multiple rowers on one boat.'}.get(error,'The analysis did not complete. See the private terminal.')
        return {'state':phase,'label':label,'detail':detail,'progress':progress,
                'has_report':bool(report and report.exists()),'has_overlay':bool(overlay and overlay.exists()),
                'elapsed_seconds':int(time.monotonic()-start) if start and phase=='running' else None,
                'crew_summary':crew_summary if phase=='finished' else None}

    def begin(self):
        with self.lock:
            if self.phase == 'running' or (self.worker and self.worker.is_alive()):return False
            if self.phase == 'finished':return False  # Exactly one fresh run in this session.
            self.cancel_requested.clear()
            self.process=None
            self.phase='running';self.error='';self.last_start=time.monotonic()
            self.report=None;self.overlay=None;self.crew_summary=None;self.log=self.root / '.oneclick-analysis.log'
            self.worker=threading.Thread(target=self._run,daemon=True)
            self.worker.start()
            return True

    def _run(self):
        log = self.log
        try:
            with log.open('wb') as out:
                cmd = self.command_factory()
                if not isinstance(cmd, list) or not cmd or not all(isinstance(i, str) for i in cmd):
                    raise ValueError('bad_command')
                if self.cancel_requested.is_set():
                    return
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                    cwd=str(Path(__file__).resolve().parents[1]), close_fds=True,
                    start_new_session=(os.name == 'posix'),
                )
                with self.lock:
                    self.process = proc
                # Covers cancellation between the pre-spawn check and Popen.
                if self.cancel_requested.is_set():
                    self._stop_process(proc)
                try:
                    ret = proc.wait(timeout=MAX_DURATION_SECONDS)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == 'posix':
                            os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.kill()
                    except (OSError, ProcessLookupError):
                        pass
                    proc.wait(timeout=10)
                    with self.lock:
                        self.phase = 'failed'
                        self.error = 'analysis_timeout'
                    return
                finally:
                    with self.lock:
                        if self.process is proc:
                            self.process = None
            if self.cancel_requested.is_set():
                return
            if ret != 0:
                with self.lock:
                    self.phase = 'failed'
                    self.error = 'analysis_failed'
                return
            # The output root is dedicated to this one-click demo, with no existing reports.
            found = sorted(self.root.rglob('report.html'), key=lambda p: p.stat().st_mtime, reverse=True)
            if not found:
                with self.lock:
                    self.phase = 'failed'
                    self.error = 'no_usable_strokes'
                return
            report = found[0]
            if not _safe_result(self.root, report) or report.stat().st_size > 16 * 1024 * 1024:
                with self.lock:
                    self.phase = 'failed'
                    self.error = 'analysis_failed'
                return
            meta = report.parent / 'metrics.json'
            if not _safe_result(self.root, meta) or meta.stat().st_size > MAX_METRICS_BYTES:
                with self.lock:
                    self.phase = 'failed'
                    self.error = 'invalid_crew_metrics'
                return
            try:
                with meta.open('rb') as stream:
                    metrics = json.load(stream)
                crew_summary = summarize_crew_metrics(metrics)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                error = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                    'invalid_crew_metrics', 'invalid_crew_rower', 'invalid_crew_cadence',
                    'no_usable_crew_tracks', 'no_usable_strokes') else 'invalid_crew_metrics'
                with self.lock:
                    self.phase = 'failed'
                    self.error = error
                return
            overlay = next((x for x in sorted(report.parent.glob('*_annotated.*'))
                            if x.suffix.lower() in ('.mp4', '.webm') and _safe_result(self.root, x)), None)
            with self.lock:
                if self.cancel_requested.is_set():
                    return
                self.report = report
                self.overlay = overlay
                self.crew_summary = crew_summary
                self.phase = 'finished'
                self.error = ''
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                self.phase = 'failed'
                self.error = 'analysis_failed'
        finally:
            with self.lock:
                self.process = None
                if self.cancel_requested.is_set():
                    self.phase = 'failed'
                    self.error = 'analysis_cancelled'
                    self.report = self.overlay = self.crew_summary = None


def create_server(video, *, output_dir=None, port=8768, command_factory=None):
    prepared=Path(video).expanduser().resolve(strict=True)
    dest=Path(output_dir).expanduser() if output_dir is not None else prepared.parent / 'oneclick-results'
    state=DemoState(prepared,dest,command_factory=command_factory)
    csrf=secrets.token_urlsafe(32)
    nonce=secrets.token_urlsafe(18)
    class Handler(BaseHTTPRequestHandler):
        server_version = 'StrokeSenseOneClick/1'
        def log_message(self,fmt,*args):pass
        def secure(self,post=False):
            host=self.headers.get_all('Host') or []
            valid={f'127.0.0.1:{self.server.server_address[1]}',f'localhost:{self.server.server_address[1]}'}
            if len(host)!=1 or host[0] not in valid:return False
            if post and (self.headers.get_all('Origin') or [])!=[f'http://{host[0]}']:return False
            return True
        def send_bytes(self,code,body=b'',mime='application/json',headers=None,csp=None):
            self.send_response(code)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',csp or "default-src 'none'; frame-ancestors 'none'")
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(body)
        def json_reply(self,code,value):self.send_bytes(code,json.dumps(value,separators=(',',':')).encode())
        def media(self,path,mime):
            total=path.stat().st_size
            status,first,last,headers=_safe_media(path,self.headers.get('Range'),head=True,mime=mime)
            if status==416:self.send_bytes(416,b'',headers=headers);return
            self.send_response(status)
            for key,value in headers.items():self.send_header(key,value)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; media-src 'self'")
            self.end_headers()
            if self.command=='HEAD':return
            with path.open('rb') as fp:
                fp.seek(first)
                remaining=last-first+1
                while remaining:
                    data=fp.read(min(65536,remaining))
                    if not data:break
                    self.wfile.write(data);remaining-=len(data)
        def do_HEAD(self):self.do_GET()
        def do_GET(self):
            if not self.secure():self.json_reply(403,{'error':'local_only'});return
            path=self.path.split('?',1)[0]
            if path=='/':
                csp=("default-src 'none'; style-src 'nonce-"+nonce+"'; script-src 'nonce-"+nonce+
                     "'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                body=PAGE.replace('__NONCE__',nonce).replace('__CSRF_JSON__',json.dumps(csrf)).encode()
                self.send_bytes(200,body,'text/html; charset=utf-8',csp=csp);return
            if path=='/api/status':self.json_reply(200,state.snapshot());return
            if path=='/video':self.media(state.video,mimetypes.guess_type(state.video.name)[0] or 'video/mp4');return
            if path=='/report':
                snap=state.snapshot()
                if not snap['has_report'] or snap['state']!='finished':self.json_reply(404,{'error':'report_not_ready'});return
                report=state.report
                if not _safe_result(state.root,report):self.json_reply(404,{'error':'invalid_report'});return
                data=report.read_bytes()
                csp="sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'"
                self.send_bytes(200,data,'text/html; charset=utf-8',csp=csp);return
            if path=='/annotated':
                snap=state.snapshot()
                if not snap['has_overlay'] or snap['state']!='finished':self.json_reply(404,{'error':'overlay_not_ready'});return
                overlay=state.overlay
                if not _safe_result(state.root,overlay):self.json_reply(404,{'error':'invalid_overlay'});return
                self.media(overlay,mimetypes.guess_type(overlay.name)[0] or 'video/mp4');return
            self.json_reply(404,{'error':'not_found'})
        def do_POST(self):
            if not self.secure(post=True) or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),csrf):
                self.json_reply(403,{'error':'origin_or_csrf_required'});return
            if self.path!='/api/analyze':self.json_reply(404,{'error':'not_found'});return
            lengths=self.headers.get_all('Content-Length') or []
            if len(lengths)!=1 or lengths[0]!='2' or self.headers.get('Content-Type')!='application/json':
                self.json_reply(400,{'error':'expected_empty_json_body'});return
            if self.rfile.read(2)!=b'{}':self.json_reply(400,{'error':'invalid_body'});return
            if not state.begin():self.json_reply(409,{'error':'already_running_or_finished'});return
            self.json_reply(202,{'started':True})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.state=state
    server.csrf=csrf
    return server


def main(argv=None):
    parser=argparse.ArgumentParser(description='Run a private local StrokeSense eights demo with one-click real inference')
    parser.add_argument('--video',required=True,help='The prepared 16-second eights clip')
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--out',default=None)
    args=parser.parse_args(argv)
    server=create_server(args.video,port=args.port,output_dir=args.out)
    print(f'StrokeSense one-click demo: http://127.0.0.1:{server.server_address[1]}',flush=True)
    print('Model setup: pip install -r requirements.txt; first run may download the pose model.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':
    main()
