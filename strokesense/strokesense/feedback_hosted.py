"""HTTPS ASGI gateway for the existing private review app; no model inference.

The unchanged review handler runs on a private ephemeral loopback port. The
public Uvicorn listener independently validates the configured public origin,
adds invitation access, secure cookies and owner-only initial provisioning.
Only validated traffic is forwarded with the internal loopback host/origin.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit
import zipfile

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse, RedirectResponse
from starlette.routing import Route
from .feedback import create_server, MAX_BODY
from .feedback_pack import install_pack, MAX_UPLOAD
from .feedback_sharing import mint_invitation, verify_invitation, study_readiness

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "media-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
       "base-uri 'none'; form-action 'self'")
ASSETS = Path(__file__).with_name('hosted_assets')


def create_app(*, data_dir=None, origin=None, owner_key=None, review_code=None, expected_clips=None):
    root = Path(data_dir or os.environ.get('STROKESENSE_DATA_DIR', '/var/data')).resolve()
    origin = (origin or os.environ.get('STROKESENSE_PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL', '')).rstrip('/')
    owner = owner_key or os.environ.get('STROKESENSE_OWNER_KEY', '')
    invite = review_code or os.environ.get('STROKESENSE_REVIEW_CODE', '')
    u = urlsplit(origin)
    if (u.scheme != 'https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment
            or not re.fullmatch(r'[a-z0-9.-]+(?::[0-9]+)?', u.netloc) or '*' in u.netloc):
        raise ValueError('an_exact_https_public_origin_is_required')
    if not 32 <= len(owner) <= 256 or not 16 <= len(invite) <= 256 or owner == invite:
        raise ValueError('distinct_owner_and_reviewer_secrets_required')
    expected = int(os.environ.get('STROKESENSE_EXPECTED_CLIPS', '7')) if expected_clips is None else expected_clips
    if type(expected) is not int or not 1 <= expected <= 100:
        raise ValueError('invalid_expected_study_count')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    csrf = hmac.new(owner.encode(), b'hosting-csrf-v1', hashlib.sha256).hexdigest()
    lock = threading.Lock()
    state = {'server': None, 'thread': None, 'http': None, 'failures': [], 'writes': [], 'catalog_digest': None}

    def start_backend():
        if state['server'] or not (root / 'study/catalog.json').is_file():
            return
        private = root / 'study/.feedback'
        private.mkdir(exist_ok=True, mode=0o700)
        key = private / 'owner.key'
        if key.exists() and not hmac.compare_digest(key.read_text().strip(), owner):
            raise ValueError('owner_key_does_not_match_persistent_study')
        if not key.exists():
            with key.open('x') as f:
                f.write(owner)
            key.chmod(0o600)
        server = create_server(root / 'study', port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        state.update(server=server, thread=thread, catalog_digest=hashlib.sha256((root/'study/catalog.json').read_bytes()).hexdigest())

    @asynccontextmanager
    async def lifespan(app):
        start_backend()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                timeout=httpx.Timeout(30., read=120.), limits=httpx.Limits(max_connections=24)) as client:
            state['http'] = client
            try:
                yield
            finally:
                if state['server']:
                    await run_in_threadpool(state['server'].shutdown)
                    state['thread'].join(3)
                    state['server'].server_close()

    def owner_ok(request):
        value = request.headers.get('authorization', '')
        return hmac.compare_digest(value.encode(), ('Bearer ' + owner).encode())

    def access_token(expiry=None):
        expiry = str(expiry if expiry is not None else int(time.time()) + 7 * 86400)
        signature = hmac.new(owner.encode(), ('access:' + expiry + ':' + invite).encode(), hashlib.sha256).hexdigest()
        return expiry + '.' + signature

    def invited(request):
        token = request.cookies.get('ss_access', '')
        if not re.fullmatch(r'[0-9]{10}\.[a-f0-9]{64}', token):
            return False
        expiry, signature = token.split('.')
        expected = hmac.new(owner.encode(), ('access:' + expiry + ':' + invite).encode(), hashlib.sha256).hexdigest()
        return int(expiry) > time.time() and hmac.compare_digest(signature, expected)

    def err(status, reason):
        return JSONResponse({'error': reason}, status_code=status)

    async def small_body(request):
        data = bytearray()
        async for block in request.stream():
            data.extend(block)
            if len(data) > MAX_BODY:
                raise OverflowError('request_too_large')
        return bytes(data)

    async def handle(request: Request):
        path = request.url.path
        if request.method not in ('GET', 'HEAD', 'POST'):
            return err(405, 'method_not_allowed')
        if path == '/healthz' and request.method in ('GET', 'HEAD'):
            # Liveness must work for Render's internal health probes as well.
            readiness = study_readiness(root / 'study', expected, state['catalog_digest'])
            return JSONResponse({'ok': True, 'study_ready': state['server'] is not None and readiness['ready'],
                                 'clip_count': readiness['clip_count'], 'expected_clips': expected})
        hosts = request.headers.getlist('host')
        origins = request.headers.getlist('origin')
        if (hosts != [u.netloc] or len(request.url.query) > 512 or len(path) > 512
                or (origins and origins != [origin])
                or (request.method == 'POST' and origins != [origin])):
            return err(403, 'same_origin_required')
        if path == '/' and request.method in ('GET', 'HEAD'):
            return RedirectResponse('/library' + ('?' + request.url.query if request.url.query else ''), status_code=307)
        if path in ('/join', '/owner') and request.method in ('GET', 'HEAD'):
            if request.url.query:
                return err(400, 'invitation_must_use_fragment')
            name = 'join.html' if path == '/join' else 'owner.html'
            return HTMLResponse((ASSETS/name).read_text())
        if path == '/api/owner/invitation':
            if request.method not in ('GET', 'HEAD'):
                return err(405, 'get_required')
            if not owner_ok(request):
                return err(403, 'owner_key_required')
            readiness = study_readiness(root/'study', expected, state['catalog_digest'])
            if not state['server'] or not readiness['ready']:
                return JSONResponse({'error':'library_not_ready','readiness':readiness}, status_code=409)
            token, expiry = mint_invitation(owner, invite, origin)
            return JSONResponse({'url':origin+'/join#invite='+token, 'expires_utc':expiry,
                                 'readiness':readiness, 'scope':'reviewer_only'})
        if path in ('/hosted.js', '/hosted.css', '/sharing.js') and request.method in ('GET', 'HEAD'):
            mime = 'application/javascript' if path.endswith('.js') else 'text/css'
            return Response((ASSETS / path[1:]).read_bytes(), media_type=mime)
        if path == '/api/hosting' and request.method in ('GET', 'HEAD'):
            return JSONResponse({'csrf': csrf, 'study_ready': state['server'] is not None})
        if path == '/setup' and request.method in ('GET', 'HEAD'):
            return HTMLResponse((ASSETS / 'setup.html').read_text())
        if path in ('/api/access', '/api/redeem', '/api/setup'):
            if request.method != 'POST':
                return err(405, 'post_required')
            if not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), csrf.encode()):
                return err(403, 'csrf_required')
            if path in ('/api/access', '/api/redeem'):
                now = time.monotonic()
                state['failures'] = [t for t in state['failures'] if now - t < 60]
                if len(state['failures']) >= 30:
                    return err(429, 'try_again_in_one_minute')
                try:
                    raw = await small_body(request)
                    data = json.loads(raw)
                    field = 'token' if path == '/api/redeem' else 'code'
                    if not isinstance(data, dict) or set(data) != {field} or not isinstance(data[field], str):
                        return err(422, 'invalid_code')
                except OverflowError:
                    return err(413, 'request_too_large')
                except (ValueError, TypeError):
                    return err(422, 'invalid_code')
                expiry = None
                if path == '/api/redeem':
                    expiry = verify_invitation(data['token'], owner, invite, origin)
                    valid = expiry is not None
                else:
                    valid = hmac.compare_digest(data['code'].encode(), invite.encode()) or hmac.compare_digest(data['code'].encode(), owner.encode())
                if not valid:
                    state['failures'].append(now)
                    return err(403, 'invitation_expired_or_invalid' if path == '/api/redeem' else 'invalid_code')
                if path == '/api/redeem':
                    readiness = study_readiness(root/'study', expected, state['catalog_digest'])
                    if not state['server'] or not readiness['ready']:
                        return err(409, 'library_not_ready')
                result = JSONResponse({'ok': True, 'next': '/library'})
                lifetime = expiry - int(time.time()) if expiry is not None else 7*86400
                result.set_cookie('ss_access', access_token(expiry), secure=True, httponly=True, samesite='strict', max_age=lifetime)
                return result
            if not owner_ok(request):
                return err(403, 'owner_key_required')
            if (root / 'study').exists():
                return err(409, 'study_already_initialized')
            if not lock.acquire(blocking=False):
                return err(409, 'setup_in_progress')
            tmp = None
            try:
                lengths = request.headers.getlist('content-length')
                if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_UPLOAD:
                    return err(413, 'package_too_large_or_missing_length')
                if request.headers.get('content-type') != 'application/zip':
                    return err(415, 'zip_required')
                with tempfile.NamedTemporaryFile(prefix='.upload-', dir=root, delete=False) as f:
                    tmp = Path(f.name)
                    size = 0
                    async for block in request.stream():
                        size += len(block)
                        if size > MAX_UPLOAD:
                            return err(413, 'package_too_large')
                        f.write(block)
                if size != int(lengths[0]):
                    return err(422, 'incomplete_upload')
                count = await run_in_threadpool(install_pack, tmp, root)
                await run_in_threadpool(start_backend)
                return JSONResponse({'installed': True, 'clip_count': count}, status_code=201)
            except FileExistsError:
                return err(409, 'study_already_initialized')
            except (ValueError, KeyError, zipfile.BadZipFile):
                return err(422, 'invalid_study_package')
            except OSError:
                return err(503, 'storage_unavailable')
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
                lock.release()
        if not invited(request):
            if path in ('/', '/library') and request.method in ('GET', 'HEAD'):
                return HTMLResponse((ASSETS / 'access.html').read_text())
            return err(401, 'review_invitation_required')
        if not state['server']:
            return err(503, 'study_not_uploaded_yet')
        if path.startswith('/api/owner/') and not owner_ok(request):
            return err(403, 'owner_key_required')
        if request.method == 'POST':
            now = time.monotonic()
            state['writes'] = [t for t in state['writes'] if now - t < 60]
            if len(state['writes']) >= 300:
                return err(429, 'write_limit_retry_later')
            state['writes'].append(now)
        try:
            body = await small_body(request) if request.method == 'POST' else b''
            backend = 'http://127.0.0.1:' + str(state['server'].server_address[1])
            headers = {k: request.headers[k] for k in ('content-type', 'cookie', 'authorization', 'x-csrf-token', 'range') if k in request.headers}
            headers['Origin'] = backend
            # Host is generated by httpx from the fixed private endpoint, never
            # copied from untrusted X-Forwarded-* input.
            target = backend + path + ('?' + request.url.query if request.url.query else '')
            msg = state['http'].build_request(request.method, target, headers=headers, content=body)
            upstream = await state['http'].send(msg, stream=True)
        except OverflowError:
            return err(413, 'request_too_large')
        except httpx.HTTPError:
            return err(503, 'review_backend_unavailable')
        allowed = ('content-type', 'content-length', 'content-range', 'accept-ranges', 'content-disposition', 'content-security-policy')
        forwarded = {k: upstream.headers[k] for k in allowed if k in upstream.headers}
        if 'set-cookie' in upstream.headers:
            forwarded['set-cookie'] = upstream.headers['set-cookie'] + '; Secure'
        async def stream():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
        return StreamingResponse(stream(), status_code=upstream.status_code, headers=forwarded)

    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault('Content-Security-Policy', CSP)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow',
            'Strict-Transport-Security':'max-age=31536000'})
        return response
    return Starlette(routes=[Route('/{path:path}', handle, methods=['GET','HEAD','POST','PUT','DELETE','PATCH','OPTIONS'])],
                     lifespan=lifespan, middleware=[Middleware(BaseHTTPMiddleware, dispatch=security_headers)])
