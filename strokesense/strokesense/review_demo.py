"""Local clip/report/LLM demonstration. No model request without explicit opt-in.

Review manifests are private operator records, not authenticated coach identities.
Structural checks never verify arbitrary model prose. No study data is modified.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading

from .correction import run_correction
from .evidence import MIN_SAMPLE_STROKES, validate_reference_graph
from .oneclick_demo import _safe_media
from .provider import OpenAIChatGenerator
from .validation import validate_candidate

MAX_METRICS = 16 * 1024 * 1024
MAX_REVIEW = 256 * 1024


def _load(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('input_too_large')
    return raw, json.loads(raw)


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def review_template(video_path, metrics_path):
    """Produce an unapproved private checklist; never invent a reviewer or result."""
    raw, metrics = _load(metrics_path, MAX_METRICS)
    snapshot = metrics.get('evidence')
    if not validate_reference_graph(snapshot):
        raise ValueError('invalid_evidence')
    return {
        'schema_version': 1, 'metrics_sha256': hashlib.sha256(raw).hexdigest(),
        'video_sha256': _sha(video_path), 'reviewed_by': '', 'reviewed_at': '',
        'confirmed_source_and_finding': False, 'finding_id': '',
        'eligible_stroke_ids': [], 'cues': {},
        'findings_for_review': snapshot['findings'],
        'strokes_for_review': snapshot['strokes'],
        'instructions': 'A real reviewer must check the source video, finding and cue. '
                        'Leave unapproved if unavailable. Do not publish this private file.',
    }


class CoachingSession:
    def __init__(self, video_path, report_path, metrics_path, *, review_path=None,
                 mode='disabled', generator_factory=None):
        if mode not in {'disabled', 'live_provider', 'test_double'}:
            raise ValueError('invalid_mode')
        self.video = Path(video_path).resolve(strict=True)
        self.report = Path(report_path).resolve(strict=True)
        self.metrics = Path(metrics_path).resolve(strict=True)
        if (not self.video.is_file() or not 0 < self.video.stat().st_size <= 150 * 1024 * 1024
                or not self.report.is_file() or self.report.stat().st_size > MAX_METRICS):
            raise ValueError('invalid_media')
        self.review = Path(review_path) if review_path else None
        self.mode = mode
        self.factory = generator_factory or OpenAIChatGenerator.from_env
        self.lock = threading.Lock()
        self.worker = None
        self.result = {'state': 'ready', 'mode': mode, 'reason': None, 'candidate': None,
                       'attempts': 0, 'warnings': [], 'evidence': []}
        try:
            self._prepare()
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.result.update(state='withheld', reason='review_required')

    def _prepare(self):
        if not self.review or not self.review.is_file():
            raise ValueError('review_required')
        raw, metrics = _load(self.metrics, MAX_METRICS)
        _, review = _load(self.review, MAX_REVIEW)
        if (not isinstance(review, dict) or review.get('schema_version') != 1
                or review.get('metrics_sha256') != hashlib.sha256(raw).hexdigest()
                or review.get('video_sha256') != _sha(self.video)):
            raise ValueError('review_source_mismatch')
        reviewer = review.get('reviewed_by')
        if (not isinstance(reviewer, str) or not reviewer.strip()
                or review.get('confirmed_source_and_finding') is not True):
            raise ValueError('review_required')
        when = datetime.fromisoformat(review['reviewed_at'].replace('Z', '+00:00'))
        if when.tzinfo is None or when > datetime.now(timezone.utc):
            raise ValueError('review_required')
        snapshot = deepcopy(metrics['evidence'])
        if not validate_reference_graph(snapshot):
            raise ValueError('invalid_evidence')
        finding = next((f for f in snapshot['findings']
                        if f['id'] == review.get('finding_id')), None)
        ids = review.get('eligible_stroke_ids')
        if (finding is None or not isinstance(ids, list)
                or any(not isinstance(s, str) for s in ids)
                or len(ids) != len(set(ids)) or len(ids) < MIN_SAMPLE_STROKES):
            raise ValueError('review_required')
        eligible = {s['id'] for s in snapshot['strokes']
                    if s['seat_id'] == finding['seat_id']}
        if not set(finding['stroke_ids']) <= set(ids) <= eligible:
            raise ValueError('review_required')
        # Only the explicitly reviewed finding becomes eligible. Input files stay unchanged.
        for f in snapshot['findings']:
            f.update(coaching_eligible=False, eligible_strokes=None,
                     status='candidate_unreviewed')
        finding.update(coaching_eligible=True, eligible_strokes=len(ids),
                       status='reviewed_supported')
        payload = {k: v for k, v in snapshot.items() if k != 'snapshot_sha256'}
        snapshot['snapshot_sha256'] = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
            allow_nan=False).encode()).hexdigest()
        cues = review.get('cues')
        if not isinstance(cues, dict) or not cues:
            raise ValueError('review_required')
        approved = {}
        for cue_id, cue in cues.items():
            probe = {k: finding[k] for k in ('seat_id', 'stroke_ids', 'fault_code',
                      'observed_count', 'analyzed_strokes', 'observed_fraction')}
            probe.update(finding_id=finding['id'], cue_id=cue_id, explanation='Preflight')
            if validate_candidate(probe, evidence_snapshot=snapshot,
                                  reviewed_cues=cues)['released'] is not None:
                approved[cue_id] = cue
        if not approved:
            raise ValueError('review_required')
        return snapshot, deepcopy(approved), finding

    def snapshot(self):
        with self.lock:
            return deepcopy(self.result)

    def begin(self):
        with self.lock:
            if self.worker is not None:
                return False
            try:
                prepared = self._prepare()
            except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                reason = ('review_source_mismatch' if str(exc) == 'review_source_mismatch'
                          else 'review_required')
                self.result.update(state='withheld', reason=reason)
                return False
            if self.mode == 'disabled':
                self.result.update(state='withheld', reason='live_not_enabled')
                return False
            self.result.update(state='generating', reason=None)
            self.worker = threading.Thread(target=self._generate, args=prepared, daemon=True)
            self.worker.start()
            return True

    def _generate(self, snapshot, cues, finding):
        try:
            generator = self.factory(snapshot, cues)
            checked = run_correction(generator, evidence_snapshot=snapshot, reviewed_cues=cues)
            candidate = checked['released']
            # A provider cannot choose a different finding than the reviewed UI selection.
            if candidate and candidate['finding_id'] != finding['id']:
                candidate = None
            evidence = [{k: s[k] for k in ('id', 'catch_seconds', 'finish_seconds')}
                        for s in snapshot['strokes'] if s['id'] in finding['stroke_ids']]
            for row in evidence:
                row['video_seek_seconds'] = row['catch_seconds'] - snapshot['start_seconds']
            result = {'state': 'draft' if candidate else 'withheld', 'mode': self.mode,
                      'reason': None if candidate else 'candidate_not_supported',
                      'candidate': candidate, 'attempts': checked['attempts'],
                      'warnings': checked['warnings'], 'evidence': evidence}
        except Exception:
            result = {'state': 'withheld', 'mode': self.mode, 'reason': 'provider_unavailable',
                      'candidate': None, 'attempts': 0, 'warnings': [], 'evidence': []}
        with self.lock:
            self.result = result


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StrokeSense | Evidence and coaching</title>
<style nonce="__NONCE__">
body{max-width:1080px;margin:32px auto;padding:0 24px;background:#f2f6f4;color:#14313a;font:18px/1.5 system-ui}
h1{font-size:40px;line-height:1.15}video{width:100%;max-height:420px;background:#102832}
button,a{font:inherit}button{padding:12px 20px;background:#17695e;color:white;border:0;border-radius:5px}
button:disabled{background:#697a76}a{color:#155c52}.status{padding:18px 0;border-block:1px solid #a9bfba}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:16px/1.5 system-ui}section{margin:28px 0}
</style><main><p>STROKESENSE / CONNECTED ALPHA DEMO</p>
<h1>Check the evidence. Then review the coaching draft.</h1>
<p id="mode">__MODE__</p><video id="video" controls playsinline preload="metadata" src="/video"></video>
<p><a href="/report" target="_blank" rel="noopener">Open this clip's saved analysis report</a></p>
<section><h2>Evidence-grounded LLM coaching</h2>
<p>The model explains one reviewed finding. The checker validates references, quantities and cue eligibility.
Free-text explanations still need human review.</p>
<button id="generate" type="button">Generate coaching draft</button>
<p class="status" id="status" role="status" aria-live="polite">Checking prerequisites...</p>
<p id="facts"></p><pre id="draft"></pre><div id="evidence"></div></section>
<p>Saved analysis is precomputed. Generating a coaching draft is a separate model request.
This demo does not submit or change reviewer-study answers.</p></main>
<script nonce="__NONCE__">
const token=__CSRF__;const button=document.getElementById('generate');
const status=document.getElementById('status');const draft=document.getElementById('draft');
const evidence=document.getElementById('evidence');
const reasons={review_required:'Withheld: genuine review of this clip and cue is required.',
review_source_mismatch:'Withheld: the review belongs to different source files.',
live_not_enabled:'Withheld: live model access has not been enabled.',
provider_unavailable:'Withheld: the model provider could not complete the request.',
candidate_not_supported:'Withheld: the candidate did not pass the evidence checks.'};
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error();
const s=await r.json();button.disabled=s.state!=='ready';
status.textContent=s.reason?reasons[s.reason]:(s.state==='draft'?'Reference and quantity checks passed. Explanation is a draft for human review.':s.state==='generating'?'Generating and checking the draft...':'Ready to generate a coaching draft.');
draft.textContent=s.candidate?s.candidate.explanation:'';evidence.replaceChildren();
document.getElementById('facts').textContent=s.candidate?('Observed in '+s.candidate.observed_count+' of '+s.candidate.analyzed_strokes+' analyzed strokes. Checked cue: '+s.candidate.cue_id+'. Attempts: '+s.attempts+'.'):'';
for(const row of s.evidence){const p=document.createElement('p');const a=document.createElement('a');
a.href='#video';a.textContent='View supporting stroke at '+row.video_seek_seconds.toFixed(2)+' seconds in this clip';
a.addEventListener('click',()=>{document.getElementById('video').currentTime=row.video_seek_seconds});p.append(a);evidence.append(p);}
}catch(e){status.textContent='Unable to connect to the local demo.';button.disabled=true;}}
button.addEventListener('click',async()=>{button.disabled=true;try{await fetch('/api/coaching',{
method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:'{}'});}finally{await refresh();}});
refresh();setInterval(refresh,1000);
</script></html>'''


def create_server(session, *, port=8769):
    csrf, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(18)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def valid_origin(self, post=False):
            host = self.headers.get_all('Host') or []
            allowed = {f'127.0.0.1:{self.server.server_address[1]}',
                       f'localhost:{self.server.server_address[1]}'}
            return (len(host) == 1 and host[0] in allowed
                    and (not post or self.headers.get_all('Origin') == [f'http://{host[0]}']))

        def reply(self, code, data, mime='application/json', *, csp=None, extra=None):
            self.send_response(code)
            for k, v in {'Content-Type': mime, 'Content-Length': str(len(data)),
                         'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                         'Referrer-Policy': 'no-referrer',
                         'Content-Security-Policy': csp or "default-src 'none'; frame-ancestors 'none'",
                         **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.valid_origin():
                self.reply(403, b'{}'); return
            if self.path == '/':
                label = {'disabled': 'Live generation disabled. No provider is contacted.',
                         'live_provider': 'Live LLM provider. A request occurs only after you click.',
                         'test_double': 'Test double: synthetic generator and fictional test approvals. Not a live LLM.'}[session.mode]
                page = PAGE.replace('__NONCE__', nonce).replace('__CSRF__', json.dumps(csrf)).replace('__MODE__', label)
                csp = (f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
                       "connect-src 'self'; media-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.reply(200, page.encode(), 'text/html; charset=utf-8', csp=csp)
            elif self.path == '/api/status':
                self.reply(200, json.dumps(session.snapshot(), allow_nan=False).encode())
            elif self.path == '/report':
                data = session.report.read_bytes()
                if len(data) > MAX_METRICS:
                    self.reply(413, b'{}'); return
                self.reply(200, data, 'text/html; charset=utf-8',
                           csp="sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'")
            elif self.path == '/video':
                code, first, last, headers = _safe_media(session.video, self.headers.get('Range'), head=True)
                if code == 416:
                    self.reply(416, b'', extra=headers); return
                self.send_response(code)
                for k, v in {**headers, 'Cache-Control': 'no-store',
                             'X-Content-Type-Options': 'nosniff'}.items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != 'HEAD':
                    with session.video.open('rb') as stream:
                        stream.seek(first)
                        remaining = last - first + 1
                        while remaining:
                            chunk = stream.read(min(65536, remaining))
                            if not chunk: break
                            self.wfile.write(chunk); remaining -= len(chunk)
            else:
                self.reply(404, b'{}')

        def do_POST(self):
            if (not self.valid_origin(True)
                    or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), csrf)):
                self.reply(403, b'{}'); return
            if self.path != '/api/coaching':
                self.reply(404, b'{}'); return
            if (self.headers.get_all('Content-Length') != ['2']
                    or self.headers.get('Content-Type') != 'application/json'
                    or self.rfile.read(2) != b'{}'):
                self.reply(400, b'{}'); return
            self.reply(202 if session.begin() else 409, b'{}')

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.csrf = csrf
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--metrics', required=True)
    parser.add_argument('--review', help='Private, genuinely completed review manifest')
    parser.add_argument('--prepare-review', help='Write an unapproved private review template and exit')
    parser.add_argument('--live', action='store_true', help='Explicitly enable configured provider requests (may incur cost)')
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args(argv)
    if args.prepare_review:
        with Path(args.prepare_review).open('x', encoding='utf-8') as out:
            json.dump(review_template(args.video, args.metrics), out, indent=2)
        return 0
    session = CoachingSession(args.video, args.report, args.metrics, review_path=args.review,
                              mode='live_provider' if args.live else 'disabled')
    server = create_server(session, port=args.port)
    print(f'StrokeSense evidence and coaching: http://127.0.0.1:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
