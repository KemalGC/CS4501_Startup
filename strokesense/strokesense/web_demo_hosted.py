"""Compute-backed public one-click demo, isolated from StrokeSense's study database.

Host one preloaded, permission-cleared MP4 behind HTTPS. The Analyze now button
starts the real existing StrokeSense CLI in a bounded subprocess. No synthetic
results are exposed by this application and no private video is stored in git.

The owner may install the uploaded demo through /setup using a bearer key. The
reviewer study and the owner's survey are separate apps and storage trees.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
import time
import urllib.request
import unicodedata
from urllib.parse import unquote, urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from .media import plausible_container
from .oneclick_demo import PAGE, _safe_media, _safe_result, MAX_MEDIA_BYTES
from .hosted_demo_state import HostedDemoState
from .hosted_video_tabs import add_video_tabs
from .hosted_demo_ui import bridge_page, redesign_hosted_demo, restyle_report
from .hosted_dashboard import build_dashboard, _snapshot_path

PUBLIC_CSP = ("default-src 'none'; script-src 'nonce-{nonce}'; "
              "style-src 'nonce-{nonce}'; frame-src 'self'; media-src 'self'; connect-src 'self'; "
              "img-src 'self' data:; frame-ancestors 'self' https://strokesense-review.kemalgcortuk.chatgpt.site https://strokesense-review.vercel.app; "
              "base-uri 'none'; form-action 'self'")
DEFAULT_CSP = ("default-src 'none'; frame-ancestors 'self' "
               "https://strokesense-review.kemalgcortuk.chatgpt.site https://strokesense-review.vercel.app")
MEDIA_CSP = ("default-src 'none'; media-src 'self'; frame-ancestors 'self' "
             "https://strokesense-review.kemalgcortuk.chatgpt.site https://strokesense-review.vercel.app")
IMAGE_CSP = MEDIA_CSP.replace("media-src 'self'", "img-src 'self'")
REPORT_CSP = ("sandbox; default-src 'none'; img-src data:; "
              "style-src 'unsafe-inline'; frame-ancestors 'self' "
              "https://strokesense-review.kemalgcortuk.chatgpt.site https://strokesense-review.vercel.app")
DEMO_SOURCE_URL = "https://strokesense-review.kemalgcortuk.chatgpt.site/demo-media/strokesense-demo.mp4"
VISITOR_UPLOAD_BYTES = 100 * 1024 * 1024
VISITOR_UPLOAD_COUNT = 3
VISITOR_UPLOAD_TTL = 60 * 60 * 2
VISITOR_GLOBAL_HOURLY_LIMIT = 24
VISITOR_CLIENT_HOURLY_LIMIT = 6
UPLOAD_DEADLINE_SECONDS = 180
UPLOAD_IDLE_SECONDS = 20
CONTROL_BODY_DEADLINE_SECONDS = 10
ANALYSIS_GLOBAL_HOURLY_LIMIT = 24
VISITOR_MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
VISITOR_ID = re.compile(r"[0-9a-f]{48}\Z")


def _visitor_name(value, *, encoded=True):
    """Use a filename for display only, never as part of a filesystem path."""
    if not isinstance(value, str):
        return None
    try:
        name = unquote(value, encoding="utf-8", errors="strict") if encoded else value
    except (UnicodeDecodeError, ValueError):
        return None
    if not 1 <= len(name) <= 120 or any(c in name for c in "\\/\r\n\0"):
        return None
    ext = Path(name).suffix.lower()
    return (name, ext) if ext in VISITOR_MEDIA_TYPES else None

def _visitor_display_name(value, *, encoded=True):
    """Display-only label: never used as a file path or analysis input."""
    if not isinstance(value, str):
        return None
    try:
        name = unquote(value, encoding="utf-8", errors="strict") if encoded else value
    except (UnicodeDecodeError, ValueError):
        return None
    name = name.strip()
    if not 1 <= len(name) <= 120 or any(
            c in ("/", chr(92)) or unicodedata.category(c)[0] == "C"
            or unicodedata.category(c) in ("Zl", "Zp")
            or ord(c) in (0x034F, 0xFE0E, 0xFE0F)
            for c in name):
        return None
    return name



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
    page = page.replace("button.disabled=data.state==='running'||data.state==='finished';", "button.disabled=data.state==='running'||data.can_rerun===false;")
    page = page.replace("data.state==='finished'?'Analysis finished'", "data.state==='finished'?'Run analysis again'")
    page = page.replace("Click once to start actual inference on this clip. The button does not replay a precomputed result.",
                        "Run pose detection and stroke analysis, then generate coaching feedback with a language model. You can open the latest report or run a fresh analysis.")
    page = page.replace('src="/video"', 'src="/demo/video"')
    page = page.replace('href="/report"', 'href="/demo/report"')
    page = page.replace('href="/annotated"', 'href="/demo/annotated"')
    page = page.replace("fetch('/api/status'", "fetch('/api/demo/status'")
    page = page.replace("fetch('/api/analyze'", "fetch('/api/demo/analyze'")
    page = page.replace("'x-csrf-token':token", "'x-demo-csrf':token")
    page = redesign_hosted_demo(add_video_tabs(page))
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
    visitor_root = demo_root / "visitor-uploads"
    if visitor_root.is_symlink():
        raise ValueError("unsafe_visitor_directory")
    visitor_root.mkdir(mode=0o700, exist_ok=True)
    lock = threading.Lock()
    upload_gate = threading.Lock()
    analysis_gate = threading.Lock()
    queue_wake = threading.Event()
    queue_thread = None
    data = {"demo": None, "uploads": {}}
    upload_history = []
    csrf = secrets.token_urlsafe(32)
    analysis_history = []
    bootstrap_status = {"state": "not_configured"}

    def fresh_state():
        if work_dir.is_symlink():
            raise ValueError("unsafe_output_directory")
        work_dir.mkdir(mode=0o700, exist_ok=True)
        return HostedDemoState(video_path, work_dir, command_factory=command_factory)

    if video_path.is_file():
        data["demo"] = fresh_state()
        bootstrap_status["state"] = "ready"

    def analysis_busy():
        prepared = data["demo"]
        return (prepared is not None and prepared.snapshot()["state"] in ("running", "stopping")
                or any(entry["state"].snapshot()["state"] in ("running", "stopping")
                       for entry in data["uploads"].values()))

    def queue_pending():
        return any(entry.get("queued", False) for entry in data["uploads"].values())

    def visitor_snapshot(entry):
        if entry.get("queued"):
            return {"state": "queued", "label": "Waiting for Render analysis",
                "detail": "Your video was uploaded successfully. Render will start its full analysis automatically when the current job finishes.",
                "progress": 0, "has_report": False, "has_overlay": False,
                "elapsed_seconds": None, "crew_summary": None,
                "llm_feedback": {"state": "pending"}, "can_rerun": False}
        status = entry["state"].snapshot()
        if entry.get("cancelled") and status["state"] != "stopping":
            return {"state": "cancelled", "label": "Analysis cancelled",
                "detail": "Analysis stopped. Your video is still available.",
                "progress": 0, "has_report": False, "has_overlay": False,
                "elapsed_seconds": None, "crew_summary": None,
                "llm_feedback": {"state": "cancelled"}, "can_rerun": True}
        return status

    def visitor_entry(job_id):
        """Enforce temporary-upload expiration on every read or rerun."""
        entry = data["uploads"].get(job_id)
        if (entry is not None and time.time() - entry["created"] > VISITOR_UPLOAD_TTL
                and entry["state"].snapshot()["state"] not in ("running", "stopping")):
            return None
        return entry

    def visitor_quota_open(request):
        """Bound public paid-CPU work, even after completed jobs are evicted."""
        now = time.time()
        upload_history[:] = [(at, client) for at, client in upload_history if now - at < 3600]
        client = request.client.host if request.client else "unknown"
        return (len(upload_history) < VISITOR_GLOBAL_HOURLY_LIMIT and
                sum(previous == client for _, previous in upload_history) < VISITOR_CLIENT_HOURLY_LIMIT)

    def analysis_quota_open():
        """Limit public inference starts, including reruns of the prepared clip."""
        now = time.time()
        analysis_history[:] = [at for at in analysis_history if now - at < 3600]
        return len(analysis_history) < ANALYSIS_GLOBAL_HOURLY_LIMIT

    def record_analysis_start():
        analysis_history.append(time.time())

    def load_uploads():
        # A Render restart must not silently swap an uploaded report with the
        # prepared report. Each private-id directory restores only its own run.
        now = time.time()
        for folder in sorted(visitor_root.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or not VISITOR_ID.fullmatch(folder.name):
                continue
            try:
                meta_path = folder / "upload.json"
                if meta_path.is_symlink() or meta_path.stat().st_size > 1024:
                    continue
                meta = json.loads(meta_path.read_text())
                name = _visitor_name(meta["name"], encoded=False)
                display = (_visitor_display_name(meta.get("display_name"), encoded=False)
                           if "display_name" in meta else
                           _visitor_display_name(name[0], encoded=False) if name else None)
                created = meta["created"]
                delete_token = meta.get("delete_token")
                if delete_token is not None and (not isinstance(delete_token, str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", delete_token)):
                    continue
                if (not name or not display or type(created) not in (int, float) or created > now + 60
                        or now - created > VISITOR_UPLOAD_TTL):
                    shutil.rmtree(folder)
                    continue
                media_path = folder / ("input" + name[1])
                if media_path.is_symlink() or not media_path.is_file():
                    continue
                state = HostedDemoState(media_path, folder / "outputs", command_factory=command_factory)
                cancelled = meta.get("cancelled") is True
                data["uploads"][folder.name] = {"name": display, "filename": name[0],
                    "created": created, "state": state, "video": media_path, "root": folder,
                    "delete_token": delete_token, "cancelled": cancelled,
                    "queued": not cancelled and bool(meta.get("auto_start")) and
                        state.snapshot()["state"] == "ready"}
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def persist_upload_state(entry, *, cancelled):
        """Atomically update resumability without deleting the visitor's source video."""
        metadata = {
            "name": entry["filename"], "display_name": entry["name"],
            "created": entry["created"], "delete_token": entry["delete_token"],
            "auto_start": False, "cancelled": cancelled,
        }
        pending = entry["root"] / (".upload-" + secrets.token_hex(10) + ".tmp")
        try:
            with pending.open("x", encoding="utf-8") as output:
                output.write(json.dumps(metadata))
            os.replace(pending, entry["root"] / "upload.json")
        finally:
            pending.unlink(missing_ok=True)

    def free_upload_slot():
        now = time.time()
        for job_id, entry in list(data["uploads"].items()):
            if (now - entry["created"] > VISITOR_UPLOAD_TTL and
                    entry["state"].snapshot()["state"] not in ("running", "stopping")):
                data["uploads"].pop(job_id)
                shutil.rmtree(entry["root"])
        if len(data["uploads"]) >= VISITOR_UPLOAD_COUNT:
            # Preserve active analysis jobs; completed reports are temporary.
            reusable = [(job_id, entry) for job_id, entry in data["uploads"].items()
                        if not entry.get("queued") and entry["state"].snapshot()["state"] not in ("running", "stopping")]
            if not reusable:
                return False
            job_id, entry = min(reusable, key=lambda item: item[1]["created"])
            data["uploads"].pop(job_id)
            shutil.rmtree(entry["root"])
        return True

    def process_queue():
        """One daemon per Render worker; never overlap CPU-heavy model jobs."""
        while True:
            queue_wake.wait(1.0)
            queue_wake.clear()
            with lock:
                with analysis_gate:
                    waiting = sorted((entry for entry in data["uploads"].values()
                                      if entry.get("queued") and
                                      time.time() - entry["created"] <= VISITOR_UPLOAD_TTL),
                                     key=lambda entry: entry["created"])
                    if waiting and not analysis_busy():
                        next_job = waiting[0]
                        if next_job["state"].begin():
                            next_job["queued"] = False

    def ensure_queue_worker():
        nonlocal queue_thread
        # Called while holding `lock`, except for single-threaded app setup.
        if queue_thread is None or not queue_thread.is_alive():
            queue_thread = threading.Thread(target=process_queue, daemon=True)
            queue_thread.start()
        queue_wake.set()

    load_uploads()
    if queue_pending():
        ensure_queue_worker()

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
                (request.method not in ("POST", "DELETE") or origins == [origin]))

    def owner_ok(request: Request):
        return hmac.compare_digest(
            request.headers.get("authorization", "").encode(),
            ("Bearer " + owner).encode()
        )

    async def bounded_body(request: Request, limit: int):
        data = bytearray()
        async with asyncio.timeout(CONTROL_BODY_DEADLINE_SECONDS):
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > limit:
                    raise OverflowError("oversize")
        return bytes(data)

    async def upload_chunks(request: Request):
        """Release the upload slot if a client stops sending body data."""
        stream = request.stream().__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(stream.__anext__(), UPLOAD_IDLE_SECONDS)
            except StopAsyncIteration:
                return
            yield chunk

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

    def snapshot_response(request, state, filename):
        """Public evidence from this completed analysis only, never disk paths."""
        if state is None or state.snapshot().get("state") != "finished":
            return reply(404, "report_not_ready")
        report = state.report
        try:
            ready = report is not None and _safe_result(state.output_root, report)
        except (OSError, ValueError):
            ready = False
        if not ready:
            return reply(404, "report_not_ready")
        path = _snapshot_path(report, state.output_root, filename)
        if path is None:
            return reply(404, "snapshot_not_found")
        return Response(path.read_bytes() if request.method == "GET" else b"",
                        media_type="image/jpeg",
                        headers={"Content-Security-Policy": IMAGE_CSP})

    async def handle(request: Request):
        route = request.url.path
        if route == "/healthz" and request.method in ("GET","HEAD"):
            return JSONResponse({"ok":True,"demo_video_ready":data["demo"] is not None,
                "demo_setup":bootstrap_status["state"],
                "version":os.environ.get("STROKESENSE_DEMO_RELEASE", "render-demo-v3")})
        if not protected(request):
            return reply(403,"same_origin_required")
        if request.method not in ("GET","HEAD","POST","DELETE"):
            return reply(405,"method_not_allowed")
        if route == "/" and request.method in ("GET","HEAD"):
            return RedirectResponse("/demo",status_code=307)
        if route == "/demo/bridge" and request.method in ("GET","HEAD"):
            page_nonce = secrets.token_urlsafe(18)
            return HTMLResponse(bridge_page(csrf, page_nonce) if request.method == "GET" else "",
                headers={"Content-Security-Policy": PUBLIC_CSP.format(nonce=page_nonce)})
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
            page_nonce = secrets.token_urlsafe(18)
            return HTMLResponse(_page(csrf,page_nonce),
                headers={"Content-Security-Policy":PUBLIC_CSP.format(nonce=page_nonce)})
        if route == "/setup" and request.method in ("GET","HEAD"):
            page_nonce = secrets.token_urlsafe(18)
            return HTMLResponse(_setup_page(page_nonce),
                headers={"Content-Security-Policy":PUBLIC_CSP.format(nonce=page_nonce)})
        if route == "/api/demo/status" and request.method in ("GET","HEAD"):
            return JSONResponse(data["demo"].snapshot()) if data["demo"] else reply(409,"video_not_ready")
        visitor_status = re.fullmatch(r"/api/demo/videos/([0-9a-f]{48})/status", route)
        if visitor_status and request.method in ("GET", "HEAD"):
            entry = visitor_entry(visitor_status.group(1))
            return JSONResponse(visitor_snapshot(entry)) if entry else reply(404, "video_not_found")
        if route == "/api/demo/dashboard" and request.method in ("GET", "HEAD"):
            demo = data["demo"]
            if demo is None or demo.snapshot()["state"] != "finished":
                return reply(404, "report_not_ready")
            try:
                result = build_dashboard(demo, "Prepared rowing clip", prepared=True)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return reply(503, "report_data_unavailable")
            return JSONResponse(result)
        visitor_dashboard = re.fullmatch(r"/api/demo/videos/([0-9a-f]{48})/dashboard", route)
        if visitor_dashboard and request.method in ("GET", "HEAD"):
            entry = visitor_entry(visitor_dashboard.group(1))
            if entry is None:
                return reply(404, "video_not_found")
            if entry.get("queued") or entry.get("cancelled") or entry["state"].snapshot()["state"] != "finished":
                return reply(404, "report_not_ready")
            try:
                result = build_dashboard(
                    entry["state"], entry["name"],
                    snapshots_base=f"/demo/videos/{visitor_dashboard.group(1)}/snapshots")
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return reply(503, "report_data_unavailable")
            return JSONResponse(result)
        visitor_snapshot_image = re.fullmatch(
            r"/demo/videos/([0-9a-f]{48})/snapshots/([^/]+)", route)
        if visitor_snapshot_image and request.method in ("GET", "HEAD"):
            entry = visitor_entry(visitor_snapshot_image.group(1))
            if entry is None:
                return reply(404, "video_not_found")
            if entry.get("queued") or entry.get("cancelled"):
                return reply(404, "report_not_ready")
            return snapshot_response(request, entry["state"], visitor_snapshot_image.group(2))
        prepared_snapshot_image = re.fullmatch(r"/demo/snapshots/([^/]+)", route)
        if prepared_snapshot_image and request.method in ("GET", "HEAD"):
            return snapshot_response(request, data["demo"], prepared_snapshot_image.group(1))
        visitor_media = re.fullmatch(r"/demo/videos/([0-9a-f]{48})/(video|report|annotated)", route)
        if visitor_media and request.method in ("GET", "HEAD"):
            entry = visitor_entry(visitor_media.group(1))
            if entry is None:
                return reply(404, "video_not_found")
            kind = visitor_media.group(2)
            if kind == "video":
                return video_response(request, entry["video"])
            state = entry["state"]
            if entry.get("cancelled") or state.snapshot()["state"] != "finished":
                return reply(404, "report_not_ready")
            path = state.report if kind == "report" else state.overlay
            if path is None or not _safe_result(state.output_root, path):
                return reply(404, "report_not_ready")
            if kind == "annotated":
                return video_response(request, path)
            if path.stat().st_size > 16 * 1024 * 1024:
                return reply(503, "report_too_large")
            return Response(restyle_report(path.read_bytes(), dark=request.query_params.get("theme") == "dark")
                if request.method == "GET" else b"",
                media_type="text/html; charset=utf-8",
                headers={"Content-Security-Policy": REPORT_CSP})
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
            return Response(restyle_report(path.read_bytes(), dark=request.query_params.get("theme") == "dark")
                if request.method == "GET" else b"",
                media_type="text/html; charset=utf-8",
                headers={"Content-Security-Policy":REPORT_CSP})
        if route == "/api/demo/analyze" and request.method == "POST":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf",""),csrf):
                return reply(403,"csrf_required")
            if request.headers.get("content-type") != "application/json":
                return reply(415,"json_required")
            try:
                raw = await bounded_body(request,2)
            except (OverflowError, TimeoutError):
                return reply(400,"expected_empty_json")
            if raw != b"{}":
                return reply(400,"expected_empty_json")
            demo=data["demo"]
            if demo is None:
                return reply(409,"video_not_ready")
            with analysis_gate:
                if not analysis_quota_open():
                    return reply(429, "analysis_rate_limited")
                if analysis_busy() or queue_pending() or not demo.begin():
                    return reply(409,"analysis_already_started")
                record_analysis_start()
            return JSONResponse({"started":True},status_code=202)
        visitor_analyze = re.fullmatch(r"/api/demo/videos/([0-9a-f]{48})/analyze", route)
        if visitor_analyze and request.method == "POST":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf", ""), csrf):
                return reply(403, "csrf_required")
            if request.headers.get("content-type") != "application/json":
                return reply(415, "json_required")
            try:
                raw = await bounded_body(request, 2)
            except (OverflowError, TimeoutError):
                return reply(400, "expected_empty_json")
            if raw != b"{}":
                return reply(400, "expected_empty_json")
            entry = visitor_entry(visitor_analyze.group(1))
            if entry is None:
                return reply(404, "video_not_found")
            delete_token = entry.get("delete_token")
            if delete_token and not hmac.compare_digest(
                    request.headers.get("x-demo-delete-token", ""), delete_token):
                return reply(403, "delete_token_required")
            with analysis_gate:
                if not analysis_quota_open():
                    return reply(429, "analysis_rate_limited")
                if entry.get("queued") or analysis_busy() or queue_pending():
                    return reply(409, "analysis_in_progress")
                if entry.get("cancelled"):
                    try:
                        persist_upload_state(entry, cancelled=False)
                    except OSError:
                        return reply(503, "unable_to_restart_analysis")
                if not entry["state"].begin():
                    return reply(409, "analysis_in_progress")
                record_analysis_start()
                entry["cancelled"] = False
            return JSONResponse({"started": True}, status_code=202)
        visitor_cancel = re.fullmatch(r"/api/demo/videos/([0-9a-f]{48})/cancel", route)
        if visitor_cancel and request.method == "POST":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf", ""), csrf):
                return reply(403, "csrf_required")
            if request.headers.get("content-type") != "application/json":
                return reply(415, "json_required")
            try:
                raw = await bounded_body(request, 2)
            except (OverflowError, TimeoutError):
                return reply(400, "expected_empty_json")
            if raw != b"{}":
                return reply(400, "expected_empty_json")
            acquired = False
            for attempt in range(20):
                if lock.acquire(blocking=False):
                    acquired = True
                    break
                await asyncio.sleep(0.05)
            if not acquired:
                return reply(409, "upload_in_progress")
            try:
                with analysis_gate:
                    entry = visitor_entry(visitor_cancel.group(1))
                    if entry is None:
                        return reply(404, "video_not_found")
                    delete_token = entry.get("delete_token")
                    if delete_token and not hmac.compare_digest(
                            request.headers.get("x-demo-delete-token", ""), delete_token):
                        return reply(403, "delete_token_required")
                    if entry.get("cancelled"):
                        status = visitor_snapshot(entry)
                        return JSONResponse({"cancellation_requested": True,
                            "state": status["state"]})
                    if entry.get("queued"):
                        try:
                            persist_upload_state(entry, cancelled=True)
                        except OSError:
                            return reply(503, "cancel_not_saved")
                        entry["queued"] = False
                        entry["cancelled"] = True
                        queue_wake.set()
                        return JSONResponse({"cancellation_requested": True, "state": "cancelled"})
                    status = entry["state"].snapshot()
                    if status["state"] not in ("running", "stopping"):
                        return reply(409, "analysis_not_running")
                    if not entry["state"].cancel():
                        return reply(409, "analysis_not_running")
                    entry["cancelled"] = True
                    persisted = True
                    try:
                        persist_upload_state(entry, cancelled=True)
                    except OSError:
                        persisted = False
                    # The worker may still be terminating; status polling confirms completion.
                    status = visitor_snapshot(entry)
                    return JSONResponse({"cancellation_requested": True, "state": status["state"],
                        "persisted": persisted}, status_code=202 if status["state"] == "stopping" else 200)
            finally:
                lock.release()

        visitor_delete = re.fullmatch(r"/api/demo/videos/([0-9a-f]{48})", route)
        if visitor_delete and request.method == "DELETE":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf", ""), csrf):
                return reply(403, "csrf_required")
            if not lock.acquire(blocking=False):
                return reply(409, "upload_in_progress")
            try:
                with analysis_gate:
                    job_id = visitor_delete.group(1)
                    entry = visitor_entry(job_id)
                    if entry is None:
                        return reply(404, "video_not_found")
                    delete_token = entry.get("delete_token")
                    # Clips created before removal was added had no per-clip
                    # token. Their unpredictable 192-bit ID remains the only
                    # bearer capability for the rest of their two-hour life.
                    if delete_token and not hmac.compare_digest(
                            request.headers.get("x-demo-delete-token", ""), delete_token):
                        return reply(403, "delete_token_required")
                    snapshot = entry["state"].snapshot()
                    if snapshot["state"] == "running" or not snapshot["can_rerun"]:
                        return reply(409, "analysis_in_progress")
                    try:
                        shutil.rmtree(entry["root"])
                    except OSError:
                        return reply(503, "unable_to_remove_video")
                    data["uploads"].pop(job_id, None)
                return JSONResponse({"removed": True, "id": job_id})
            finally:
                lock.release()
        if route == "/api/demo/videos" and request.method == "POST":
            if not hmac.compare_digest(request.headers.get("x-demo-csrf", ""), csrf):
                return reply(403, "csrf_required")
            name = _visitor_name(request.headers.get("x-demo-filename", ""))
            if not name or request.headers.get("content-type") != VISITOR_MEDIA_TYPES[name[1]]:
                return reply(415, "supported_video_required")
            display_header = request.headers.get("x-demo-display-name")
            display_name = (_visitor_display_name(display_header) if display_header is not None
                            else _visitor_display_name(name[0], encoded=False))
            if not display_name:
                return reply(422, "invalid_display_name")
            limit = min(upper, VISITOR_UPLOAD_BYTES)
            lengths = request.headers.getlist("content-length")
            if len(lengths) > 1 or (lengths and not lengths[0].isdigit()):
                return reply(411, "invalid_content_length")
            if lengths and not 0 < int(lengths[0]) <= limit:
                return reply(413, "video_too_large")
            if not upload_gate.acquire(blocking=False):
                return reply(409, "upload_in_progress")
            pending = None
            folder = None
            try:
                if not visitor_quota_open(request):
                    return reply(429, "upload_rate_limited")
                with tempfile.NamedTemporaryFile(dir=visitor_root, prefix=".upload-", delete=False) as stream:
                    pending = Path(stream.name)
                    total = 0
                    header = bytearray()
                    try:
                        async with asyncio.timeout(UPLOAD_DEADLINE_SECONDS):
                            async for chunk in upload_chunks(request):
                                total += len(chunk)
                                if total > limit:
                                    return reply(413, "video_too_large")
                                if len(header) < 4096:
                                    header.extend(chunk[:4096 - len(header)])
                                stream.write(chunk)
                    except TimeoutError:
                        return reply(408, "upload_timed_out")
                if total < 1 or (lengths and total != int(lengths[0])):
                    return reply(422, "incomplete_video")
                if not plausible_container(bytes(header), name[1], total_size=total):
                    return reply(422, "invalid_video_container")
                # Keep the state lock clear while a remote client streams bytes.
                # Cancellation and deletion of existing clips must remain usable.
                with lock:
                    if not visitor_quota_open(request):
                        return reply(429, "upload_rate_limited")
                    if not free_upload_slot():
                        return reply(429, "analysis_capacity_reached")
                    job_id = secrets.token_hex(24)
                    folder = visitor_root / job_id
                    folder.mkdir(mode=0o700)
                    media_path = folder / ("input" + name[1])
                    os.chmod(pending, 0o600)
                    os.replace(pending, media_path)
                    pending = None
                    created = time.time()
                    delete_token = secrets.token_urlsafe(32)
                    (folder / "upload.json").write_text(json.dumps({
                        "name": name[0], "display_name": display_name, "created": created,
                        "delete_token": delete_token, "auto_start": True, "cancelled": False,
                    }))
                    state = HostedDemoState(media_path, folder / "outputs", command_factory=command_factory)
                    with analysis_gate:
                        queued = analysis_busy() or queue_pending()
                        if not queued and not state.begin():
                            return reply(503, "unable_to_start_analysis")
                        data["uploads"][job_id] = {"name": display_name, "filename": name[0],
                                                    "created": created, "state": state,
                                                    "video": media_path, "root": folder,
                                                    "delete_token": delete_token, "queued": queued,
                                                    "cancelled": False}
                        upload_history.append((created, request.client.host if request.client else "unknown"))
                    if queued:
                        ensure_queue_worker()
                    folder = None
                    return JSONResponse({"id": job_id, "name": display_name,
                        "started": not queued, "queued": queued,
                        "delete_token": delete_token,
                        "status_url": f"/api/demo/videos/{job_id}/status",
                        "video_url": f"/demo/videos/{job_id}/video",
                        "report_url": f"/demo/videos/{job_id}/report",
                        "annotated_url": f"/demo/videos/{job_id}/annotated"}, status_code=202)
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)
                if folder is not None:
                    shutil.rmtree(folder)
                upload_gate.release()
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
            if not upload_gate.acquire(blocking=False):
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
                    try:
                        async with asyncio.timeout(UPLOAD_DEADLINE_SECONDS):
                            async for chunk in upload_chunks(request):
                                total+=len(chunk)
                                if total > upper:
                                    return reply(413,"video_too_large")
                                if len(header)<4096:
                                    header.extend(chunk[:4096-len(header)])
                                digest.update(chunk)
                                fp.write(chunk)
                    except TimeoutError:
                        return reply(408,"upload_timed_out")
                if total != declared:
                    return reply(422,"incomplete_video")
                if not plausible_container(bytes(header),".mp4",total_size=total):
                    return reply(422,"invalid_video_container")
                with lock:
                    if data["demo"] is not None or video_path.exists():
                        return reply(409,"demo_already_prepared")
                    os.chmod(temp,0o600)
                    os.replace(temp,video_path)
                    temp=None
                    data["demo"] = fresh_state()
                    return JSONResponse({"prepared":True,"size_bytes":total,
                        "sha256":digest.hexdigest(),"next":"/demo"},status_code=201)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
                upload_gate.release()
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
