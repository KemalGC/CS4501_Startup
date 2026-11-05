"""Compute-backed public one-click demo, isolated from StrokeSense's study database.

Host one preloaded, permission-cleared MP4 behind HTTPS. The Analyze now button
starts the real existing StrokeSense CLI in a bounded subprocess. No synthetic
results are exposed by this application and no private video is stored in git.

The owner may install the uploaded demo through /setup using a bearer key. The
reviewer study and the owner's survey are separate apps and storage trees.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import urllib.request
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from .media import plausible_container
from .oneclick_demo import PAGE, _safe_media, _safe_result, MAX_MEDIA_BYTES
from .hosted_demo_state import HostedDemoState

PUBLIC_CSP = ("default-src 'none'; script-src 'nonce-{nonce}'; "
              "style-src 'nonce-{nonce}'; media-src 'self'; connect-src 'self'; "
              "img-src 'self' data:; frame-ancestors 'self' https://strokesense-review.kemalgcortuk.chatgpt.site; "
              "base-uri 'none'; form-action 'self'")
DEFAULT_CSP = ("default-src 'none'; frame-ancestors 'self' "
               "https://strokesense-review.kemalgcortuk.chatgpt.site")
MEDIA_CSP = ("default-src 'none'; media-src 'self'; frame-ancestors 'self' "
             "https://strokesense-review.kemalgcortuk.chatgpt.site")
REPORT_CSP = ("sandbox; default-src 'none'; img-src data:; "
              "style-src 'unsafe-inline'; frame-ancestors 'self' "
              "https://strokesense-review.kemalgcortuk.chatgpt.site")
DEMO_SOURCE_URL = "https://strokesense-review.kemalgcortuk.chatgpt.site/demo-media/strokesense-demo.mp4"


def _install_demo_video(source_url, sha256, video_path, upper):
    """Install only the owner's declared public demo asset, with verified bytes."""
    if source_url != DEMO_SOURCE_URL or not re.fullmatch(r"[a-f0-9]{64}", sha256 or ""):
        raise ValueError("invalid_demo_source")
    if video_path.exists():
        return
    pending = None
    try:
        request = urllib.request.Request(source_url, headers={"User-Agent": "StrokeSense-Render/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.geturl() != source_url:
                raise ValueError("unexpected_demo_redirect")
            expected = response.headers.get("Content-Length")
            if expected and (not expected.isdigit() or not 0 < int(expected) <= upper):
                raise ValueError("invalid_demo_size")
            digest = hashlib.sha256()
            total = 0
            header = bytearray()
            with tempfile.NamedTemporaryFile(dir=video_path.parent, prefix=".bootstrap-", delete=False) as stream:
                pending = Path(stream.name)
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > upper:
                        raise ValueError("demo_too_large")
                    if len(header) < 4096:
                        header.extend(chunk[:4096-len(header)])
                    digest.update(chunk)
                    stream.write(chunk)
            if (not total or (expected and total != int(expected)) or digest.hexdigest() != sha256
                    or not plausible_container(bytes(header), ".mp4", total_size=total)):
                raise ValueError("demo_integrity_check_failed")
        os.chmod(pending, 0o600)
        # The caller holds the same lock used by authenticated owner uploads.
        if not video_path.exists():
            os.replace(pending, video_path)
            pending = None
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)

def _safe_origin(value: str):
    u = urlsplit(value)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.path or u.query or u.fragment or
            not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]+)?", u.netloc)):
        raise ValueError("an_exact_https_origin_is_required")
    return u.netloc


def _page(csrf: str, nonce: str):
    """Use the existing tested local demo UI with HTTPS route prefixes."""
    page = PAGE.replace("Local eights demonstration", "Hosted eights demonstration")
    page = page.replace("Local eights demonstration", "Hosted eights demonstration")
    page = page.replace("16-second eights clip", "12.8-second eights clip")
    page = page.replace("The 16-second eights clip", "The prepared 12.8-second eights clip")
    page = page.replace("IMG_5092", "Video Project 19")
    page = page.replace("Original window: 10–26 seconds of Video Project 19.MOV.",
                        "Full 12.8-second uploaded eights clip; the model runs on this footage.")
    page = page.replace("Runs on your own computer.", "Runs on the hosted CPU analysis service.")
    page = page.replace("Check the terminal running the demo.", "Contact the site owner or retry after the service recovers.")
    page = page.replace("Unable to connect to the local analysis service", "Unable to connect to the analysis service")
    page = page.replace("The demo is available only on this computer.",
                        "Separate from the seven curated study clips and participant feedback.")
    page = page.replace("The report will be computed on this exact 16-second excerpt.", "The report is computed from this exact video.")
    page = page.replace("button.disabled=data.state==='running'||data.state==='finished';", "button.disabled=data.state==='running';")
    page = page.replace("data.state==='finished'?'Analysis finished'", "data.state==='finished'?'Run analysis again'")
    page = page.replace("Click once to start actual inference on this clip. The button does not replay a precomputed result.",
                        "Run pose detection and stroke analysis on the video. You can open the latest report or run a fresh analysis.")
    page = page.replace('src="/video"', 'src="/demo/video"')
    page = page.replace('href="/report"', 'href="/demo/report"')
    page = page.replace('href="/annotated"', 'href="/demo/annotated"')
    page = page.replace("fetch('/api/status'", "fetch('/api/demo/status'")
    page = page.replace("fetch('/api/analyze'", "fetch('/api/demo/analyze'")
    page = page.replace("'x-csrf-token':token", "'x-demo-csrf':token")
    page = page.replace('__CSRF_JSON__',json.dumps(csrf))
    return page.replace('__NONCE__',nonce)


def _setup_page(nonce: str):
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StrokeSense • Prepare demo clip</title>
<style nonce="__NONCE__">
body{font:17px/1.6 system-ui,sans-serif;background:#f4f8f7;color:#142d32;margin:0}
main{max-width:650px;margin:64px auto;padding:30px;background:white;border:1px solid #d3e2de;border-radius:16px}
h1{font-size:32px;line-height:1.2}label{display:block;margin:22px 0}
input{display:block;font:inherit;width:100%;margin-top:8px;padding:12px;border:1px solid #9dafab;border-radius:9px}
button{font:700 18px system-ui;background:#0d7468;color:white;padding:14px 22px;border:0;border-radius:9px;cursor:pointer}
p{color:#50636a}#message{color:#144b42;white-space:pre-wrap}
</style></head><body><main><p>StrokeSense / Private demo setup</p>
<h1>Prepare the eights demo video</h1>
<p>The study remains unchanged. Only the site owner can upload the prepared clip.
The website will run a fresh model inference when the first visitor clicks Analyze now.
Use the 12.8-second <strong>Video Project 19 (1).mp4</strong> supplied for the demo.</p>
<form id="upload"><label>Owner key<input name="key" type="password" autocomplete="off" required></label>
<label>Prepared video (MP4; up to 150 MiB)<input name="video" type="file" accept=".mp4,video/mp4" required></label>
<button type="submit">Prepare video</button></form>
<p id="message" role="status" aria-live="polite"></p>
<a href="/demo">Go to demo</a></main>
<script nonce="__NONCE__">
document.getElementById('upload').addEventListener('submit',async (event)=>{
 event.preventDefault();const form=event.currentTarget;
 const file=form.elements.video.files[0];
 const box=document.getElementById('message');
 if(!file){box.textContent='Choose the MP4 first.';return;}
 const btn=form.querySelector('button');btn.disabled=true;box.textContent='Uploading video privately…';
 try{
  const response=await fetch('/api/owner/demo-video',{method:'POST',
     headers:{'authorization':'Bearer '+form.elements.key.value,'content-type':'video/mp4'},
     body:file,credentials:'same-origin'});
  const body=await response.json();
  if(!response.ok)throw Error(body.error||'Unable to prepare the video');
  form.elements.key.value='';
  box.textContent='Video prepared. Open the demo and click Analyze now.';
 }catch(error){box.textContent='Upload failed: '+error.message}
 finally{btn.disabled=false}
});
</script></body></html>""".replace("__NONCE__", nonce)


def create_app(*, data_dir=None, origin=None, owner_key=None,
               max_upload_bytes=None, command_factory=None, bootstrap_url=None, bootstrap_sha256=None):
    root = Path(data_dir or os.environ.get("STROKESENSE_DEMO_DATA_DIR", "/var/data")).resolve()
    origin = (origin or os.environ.get("STROKESENSE_DEMO_ORIGIN")
              or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    host = _safe_origin(origin)
    owner = owner_key or os.environ.get("STROKESENSE_DEMO_OWNER_KEY", "")
    if not 32 <= len(owner) <= 256:
        raise ValueError("a_strong_owner_key_is_required")
    upper = MAX_MEDIA_BYTES if max_upload_bytes is None else max_upload_bytes
    if type(upper) is not int or not 1 <= upper <= MAX_MEDIA_BYTES:
        raise ValueError("invalid_upload_limit")
    demo_root = root / "demo"
    demo_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    video_path = demo_root / "prepared.mp4"
    work_dir = demo_root / "outputs"
    lock = threading.Lock()
    data = {"demo": None}
    csrf = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(18)
    bootstrap_status = {"state": "not_configured"}

    def fresh_state():
        if work_dir.is_symlink():
            raise ValueError("unsafe_output_directory")
        work_dir.mkdir(mode=0o700, exist_ok=True)
        return HostedDemoState(video_path, work_dir, command_factory=command_factory)

    if video_path.is_file():
        data["demo"] = fresh_state()
        bootstrap_status["state"] = "ready"

    source_url = bootstrap_url or os.environ.get("STROKESENSE_DEMO_SOURCE_URL", "")
    source_sha256 = bootstrap_sha256 or os.environ.get("STROKESENSE_DEMO_SOURCE_SHA256", "")
    bootstrap_thread = None
    if data["demo"] is None and source_url:
        if source_url != DEMO_SOURCE_URL or not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
            raise ValueError("invalid_demo_source")
        bootstrap_status["state"] = "preparing"
        def bootstrap():
            with lock:
                try:
                    _install_demo_video(source_url, source_sha256, video_path, upper)
                    data["demo"] = fresh_state()
                    bootstrap_status["state"] = "ready"
                except (OSError, ValueError):
                    bootstrap_status["state"] = "failed"
        bootstrap_thread = threading.Thread(target=bootstrap, daemon=True)
        bootstrap_thread.start()

    def reply(status, reason):
        return JSONResponse({"error":reason},status_code=status)

    def protected(request: Request):
        hosts = request.headers.getlist("host")
        origins = request.headers.getlist("origin")
        return (hosts == [host] and len(request.url.path) <= 512
                and len(request.url.query) <= 512 and
                (not origins or origins == [origin]) and
                (request.method != "POST" or origins == [origin]))

    def owner_ok(request: Request):
        return hmac.compare_digest(
            request.headers.get("authorization", "").encode(),
            ("Bearer " + owner).encode()
        )

    async def bounded_body(request: Request, limit: int):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit:
                raise OverflowError("oversize")
        return bytes(data)

    def video_response(request, path: Path):
        if not path.is_file() or path.is_symlink():
            return reply(404,"media_not_ready")
        code, first, last, headers = _safe_media(
            path, request.headers.get("range"), head=True,
            mime=mimetypes.guess_type(path.name)[0] or "video/mp4"
        )
        # Browsers apply this policy to their generated standalone video page.
        # A default-src 'none' response without media-src blocks its own MP4.
        headers["Content-Security-Policy"] = MEDIA_CSP
        if code == 416:
            return Response(status_code=416,headers=headers)
        if request.method == "HEAD":
            return Response(status_code=code,headers=headers)
        def chunks():
            with path.open("rb") as stream:
                stream.seek(first)
                remaining = last - first + 1
                while remaining:
                    chunk = stream.read(min(65536,remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        return StreamingResponse(chunks(),status_code=code,headers=headers)

    async def handle(request: Request):
        route = request.url.path
        if route == "/healthz" and request.method in ("GET","HEAD"):
            return JSONResponse({"ok":True,"demo_video_ready":data["demo"] is not None,
                "demo_setup":bootstrap_status["state"],
                "version":os.environ.get("STROKESENSE_DEMO_RELEASE", "render-demo-v3")})
        if not protected(request):
            return reply(403,"same_origin_required")
        if request.method not in ("GET","HEAD","POST"):
            return reply(405,"method_not_allowed")
        if route == "/" and request.method in ("GET","HEAD"):
            return RedirectResponse("/demo",status_code=307)
        if route == "/demo" and request.method in ("GET","HEAD"):
            if data["demo"] is None:
                return HTMLResponse(
                    "<!doctype html><html lang='en'><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<title>StrokeSense demo setup</title>"
                    "<main style='font:18px system-ui;max-width:650px;margin:60px auto'>" +
                    ("<h1>Preparing the demo video</h1><p>The video is being transferred to the analysis service. Refresh shortly.</p>"
                     if bootstrap_status["state"] == "preparing" else
                     "<h1>Demo video not loaded yet</h1><p>The owner must prepare the video before visitors can run the model.</p>") +
                    "<a href='/setup'>Prepare the demo video</a></main></html>"
                )
            return HTMLResponse(_page(csrf,nonce),
                headers={"Content-Security-Policy":PUBLIC_CSP.format(nonce=nonce)})
        if route == "/setup" and request.method in ("GET","HEAD"):
            return HTMLResponse(_setup_page(nonce),
                headers={"Content-Security-Policy":PUBLIC_CSP.format(nonce=nonce)})
        if route == "/api/demo/status" and request.method in ("GET","HEAD"):
            return JSONResponse(data["demo"].snapshot()) if data["demo"] else reply(409,"video_not_ready")
        if route == "/demo/video" and request.method in ("GET","HEAD"):
            if data["demo"] is None:
                return reply(404,"video_not_ready")
            return video_response(request,video_path)
        if route in ("/demo/report","/demo/annotated") and request.method in ("GET","HEAD"):
            demo=data["demo"]
            if demo is None or demo.snapshot()["state"] != "finished":
                return reply(404,"report_not_ready")
            path = demo.report if route == "/demo/report" else demo.overlay
            if path is None or not _safe_result(work_dir,path):
                return reply(404,"report_not_ready")
            if route == "/demo/annotated":
                return video_response(request,path)
            if path.stat().st_size > 16 * 1024 * 1024:
                return reply(503,"report_too_large")
            return Response(path.read_bytes() if request.method == "GET" else b"",
                media_type="text/html; charset=utf-8",
                headers={"Content-Security-Policy":REPORT_CSP})
        if route == "/api/demo/analyze" and request.method == "POST":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf",""),csrf):
                return reply(403,"csrf_required")
            if request.headers.get("content-type") != "application/json":
                return reply(415,"json_required")
            try:
                raw = await bounded_body(request,2)
            except OverflowError:
                return reply(400,"expected_empty_json")
            if raw != b"{}":
                return reply(400,"expected_empty_json")
            demo=data["demo"]
            if demo is None:
                return reply(409,"video_not_ready")
            if not demo.begin():
                return reply(409,"analysis_already_started")
            return JSONResponse({"started":True},status_code=202)
        if route == "/api/owner/demo-video" and request.method == "POST":
            if not owner_ok(request):
                return reply(403,"owner_key_required")
            if request.headers.get("content-type") != "video/mp4":
                return reply(415,"mp4_required")
            lengths=request.headers.getlist("content-length")
            if len(lengths)!=1 or not lengths[0].isdigit():
                return reply(411,"content_length_required")
            declared=int(lengths[0])
            if not 0 < declared <= upper:
                return reply(413,"video_too_large")
            if not lock.acquire(blocking=False):
                return reply(409,"upload_in_progress")
            temp = None
            try:
                if data["demo"] is not None or video_path.exists():
                    return reply(409,"demo_already_prepared")
                with tempfile.NamedTemporaryFile(dir=demo_root,prefix=".upload-",delete=False) as fp:
                    temp = Path(fp.name)
                    total=0
                    digest=hashlib.sha256()
                    header=bytearray()
                    async for chunk in request.stream():
                        total+=len(chunk)
                        if total > upper:
                            return reply(413,"video_too_large")
                        if len(header)<4096:
                            header.extend(chunk[:4096-len(header)])
                        digest.update(chunk)
                        fp.write(chunk)
                if total != declared:
                    return reply(422,"incomplete_video")
                if not plausible_container(bytes(header),".mp4",total_size=total):
                    return reply(422,"invalid_video_container")
                os.chmod(temp,0o600)
                os.replace(temp,video_path)
                temp=None
                data["demo"] = fresh_state()
                return JSONResponse({"prepared":True,"size_bytes":total,
                    "sha256":digest.hexdigest(),"next":"/demo"},status_code=201)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
                lock.release()
        return reply(404,"not_found")

    async def security_headers(request, call_next):
        response=await call_next(request)
        response.headers.setdefault("Content-Security-Policy",DEFAULT_CSP)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    app=Starlette(routes=[Route("/{path:path}",handle,
                      methods=["GET","HEAD","POST","PUT","DELETE","PATCH","OPTIONS"])])
    app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers)
    app.state.demo_csrf=csrf
    app.state.bootstrap_thread=bootstrap_thread
    app.state.demo_data=data
    return app
