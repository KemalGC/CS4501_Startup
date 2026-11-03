"""Private, dependency-free athlete feedback site for curated StrokeSense results.

Run: python -m strokesense.feedback --pack PATH --port 8767
Footage and feedback remain local. Ratings are reviewer perceptions, not ground truth.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import mimetypes
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import parse_qs, urlsplit

ASPECTS = {
    'tracking': ('Rower detection & tracking', 'Does the system follow the right people without swapping or losing them?'),
    'rate': ('Stroke rate', 'Does the reported rate match the catches you can see?'),
    'position': ('Body positions & angles', 'Do the body-angle findings match the visible rower and camera view?'),
    'sequencing': ('Stroke sequencing', 'Do drive, recovery and technique flags match the observed movement?'),
    'timing': ('Crew timing', 'Do the reported catch differences match the crew in the video?'),
    'evidence': ('Evidence & explanation', 'Do the snapshots, curves and explanations support the claims and help you act?'),
}
ROLES = {'rower', 'coach', 'coxswain', 'other'}
EXPERIENCE = {'under1', '1to3', '3to5', '5plus', 'skip'}
ASSETS = Path(__file__).with_name('feedback_assets')
MAX_BODY = 16384


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('invalid_pack_path')
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('invalid_pack_path')
    return result


def load_catalog(path):
    path = Path(path).resolve()
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('catalog_too_large')
    catalog = json.loads(path.read_text(encoding='utf-8'))
    if catalog.get('schema_version') != 1 or not isinstance(catalog.get('clips'), list) or len(catalog['clips']) > 100:
        raise ValueError('invalid_catalog')
    seen = set()
    for c in catalog['clips']:
        if not re.fullmatch(r'[a-z0-9-]{1,64}', c['id']) or c['id'] in seen:
            raise ValueError('invalid_clip_id')
        seen.add(c['id'])
        if not _finite(c['duration']) or not 0 < c['duration'] <= 3600:
            raise ValueError('invalid_duration')
        for key in ('video', 'poster', 'report', 'annotated'):
            if c.get(key):
                _path(path.parent, c[key])
        analysis = c.get('analysis', {})
        if not isinstance(analysis.get('version'), str) or not analysis['version']:
            raise ValueError('analysis_revision_required')
        if set(analysis.get('aspects', {})) != set(ASPECTS):
            raise ValueError('all_aspects_required')
    return catalog


def validate_review(data, clip):
    required = {'clip_id', 'analysis_version', 'aspect_id', 'usefulness', 'accuracy', 'accuracy_reason', 'comment', 'timestamp_seconds'}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError('invalid_fields')
    if data['clip_id'] != clip['id'] or data['analysis_version'] != clip['analysis']['version']:
        raise ValueError('analysis_changed_reload')
    aspect = data['aspect_id']
    if not isinstance(aspect, str) or aspect not in ASPECTS:
        raise ValueError('invalid_aspect')
    for k in ('usefulness', 'accuracy'):
        if data[k] is not None and (type(data[k]) is not int or not 1 <= data[k] <= 5):
            raise ValueError('rating_must_be_1_to_5')
    if data['accuracy'] is None:
        if data['accuracy_reason'] not in ('cannot_judge', 'not_applicable'):
            raise ValueError('accuracy_reason_required')
    elif data['accuracy_reason'] != 'rated':
        raise ValueError('invalid_accuracy_reason')
    status = clip['analysis']['aspects'][aspect].get('status', 'unavailable')
    if status in ('unavailable', 'not_run') and data['accuracy'] is not None:
        raise ValueError('no_output_to_rate_for_accuracy')
    stamp = data['timestamp_seconds']
    if stamp is not None and (not _finite(stamp) or not 0 <= stamp <= clip['duration']):
        raise ValueError('timestamp_outside_video')
    if not isinstance(data['comment'], str) or len(data['comment']) > 2000 or '\x00' in data['comment']:
        raise ValueError('comment_too_long_or_invalid')
    return {**data, 'comment': data['comment'].strip()}


class ReviewStore:
    """Session-owned versioned upserts. Never trust a client-provided reviewer ID."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self.connect()) as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS meta(version INTEGER NOT NULL);
            INSERT INTO meta SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM meta);
            CREATE TABLE IF NOT EXISTS sessions(
              token_hash TEXT PRIMARY KEY, reviewer_id TEXT UNIQUE NOT NULL,
              role TEXT NOT NULL, experience TEXT NOT NULL, consent_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS responses(
              reviewer_id TEXT NOT NULL REFERENCES sessions(reviewer_id) ON DELETE CASCADE,
              clip_id TEXT NOT NULL, analysis_version TEXT NOT NULL, aspect_id TEXT NOT NULL,
              usefulness INTEGER, accuracy INTEGER, accuracy_reason TEXT NOT NULL,
              comment TEXT NOT NULL, timestamp_seconds REAL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
              PRIMARY KEY(reviewer_id,clip_id,analysis_version,aspect_id));
            ''')
            if c.execute('SELECT version FROM meta').fetchone()[0] != 1:
                raise ValueError('unsupported_feedback_schema')
            c.commit()
        try: self.path.chmod(0o600)
        except OSError: pass

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def enroll(self, role, experience, consent):
        if consent is not True or role not in ROLES or experience not in EXPERIENCE:
            raise ValueError('consent_and_profile_required')
        token, rid = secrets.token_urlsafe(32), secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as c, c:
            c.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), rid, role, experience, now))
        return token

    def session(self, token):
        if not token or len(token) > 100: return None
        with closing(self.connect()) as c:
            row = c.execute('SELECT reviewer_id,role,experience,consent_utc FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            return dict(row) if row else None

    def save(self, rid, row):
        now = datetime.now(timezone.utc).isoformat()
        values = (rid, row['clip_id'], row['analysis_version'], row['aspect_id'], row['usefulness'], row['accuracy'], row['accuracy_reason'], row['comment'], row['timestamp_seconds'], now, now)
        with closing(self.connect()) as c, c:
            c.execute('''INSERT INTO responses VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(reviewer_id,clip_id,analysis_version,aspect_id) DO UPDATE SET
              usefulness=excluded.usefulness,accuracy=excluded.accuracy,
              accuracy_reason=excluded.accuracy_reason,comment=excluded.comment,
              timestamp_seconds=excluded.timestamp_seconds,updated_utc=excluded.updated_utc''', values)

    def responses(self, rid, clip):
        with closing(self.connect()) as c:
            return [dict(r) for r in c.execute('SELECT * FROM responses WHERE reviewer_id=? AND clip_id=?', (rid, clip))]

    def withdraw(self, rid):
        with closing(self.connect()) as c, c:
            c.execute('DELETE FROM sessions WHERE reviewer_id=?', (rid,))

    def rows(self):
        with closing(self.connect()) as c:
            return [dict(r) for r in c.execute('SELECT r.*,s.role,s.experience FROM responses r JOIN sessions s USING(reviewer_id) ORDER BY r.updated_utc')]

    def summary(self):
        rows = self.rows(); groups = defaultdict(list)
        for r in rows: groups[(r['clip_id'], r['analysis_version'], r['aspect_id'])].append(r)
        aspects = []
        for (clip, version, aspect), group in sorted(groups.items()):
            use = [r['usefulness'] for r in group if r['usefulness'] is not None]
            acc = [r['accuracy'] for r in group if r['accuracy'] is not None]
            aspects.append({'clip_id':clip,'analysis_version':version,'aspect_id':aspect,'responses':len(group),
                'usefulness_n':len(use),'usefulness_mean':sum(use)/len(use) if use else None,
                'accuracy_n':len(acc),'accuracy_mean':sum(acc)/len(acc) if acc else None,
                'cannot_judge_n':sum(r['accuracy_reason']=='cannot_judge' for r in group),
                'not_applicable_n':sum(r['accuracy_reason']=='not_applicable' for r in group)})
        return {'reviewer_count':len({r['reviewer_id'] for r in rows}), 'response_count':len(rows), 'aspects':aspects,
                'method':'Self-reported usefulness and perceived accuracy; not labeled model accuracy. Repeated versions/recordings are not independent evidence.'}


def create_server(pack, *, port=8767, db_path=None):
    root = Path(pack).resolve(); catalog = load_catalog(root/'catalog.json')
    clips = {c['id']:c for c in catalog['clips']}
    private = root/'.feedback'; private.mkdir(exist_ok=True, mode=0o700)
    keyfile = private/'owner.key'
    if not keyfile.exists():
        keyfile.write_text(secrets.token_urlsafe(32)); keyfile.chmod(0o600)
    owner = keyfile.read_text().strip()
    store = ReviewStore(db_path or private/'reviews.sqlite3'); csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'StrokeSenseReview/1'
        def log_message(self, *args): pass  # Never log tokens, reviewer input or footage paths.
        def trusted(self):
            if len(self.path) > 512: return False
            port = self.server.server_address[1]
            valid = {f'127.0.0.1:{port}', f'localhost:{port}'}
            host = self.headers.get('Host', '')
            origins = self.headers.get_all('Origin') or []
            return host in valid and (not origins or (len(origins)==1 and origins[0]==f'http://{host}'))
        def session(self):
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get('Cookie', ''))
            except Exception: return None
            item = cookie.get('ss_review')
            return store.session(item.value if item else None)
        def owner(self):
            value = self.headers.get('Authorization', '')
            return hmac.compare_digest(value, 'Bearer '+owner)
        def send(self, code, body=b'', mime='application/json; charset=utf-8', headers=None):
            if isinstance(body, (dict, list)): body = _json(body)
            self.send_response(code)
            self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            for k,v in (headers or {}).items(): self.send_header(k,v)
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
        def error(self, code, reason): self.send(code, {'error':reason})
        def do_HEAD(self): self.do_GET()
        def do_GET(self):
            if not self.trusted(): self.error(403,'same_origin_required'); return
            parsed = urlsplit(self.path); route = parsed.path
            try:
                if route in ('/','/app.js','/style.css'):
                    name = 'index.html' if route=='/' else route[1:]
                    mime = {'index.html':'text/html; charset=utf-8','app.js':'application/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name]
                    self.send(200,(ASSETS/name).read_bytes(),mime);return
                if route=='/api/bootstrap':
                    public=[]
                    for c in clips.values():
                        item={k:c[k] for k in ('id','title','group_id','duration','analysis') if k in c}
                        item['assets']=[k for k in ('video','poster','report','annotated') if c.get(k)]
                        public.append(item)
                    self.send(200,{'schema_version':1,'csrf':csrf,'session':self.session(),'clips':public,
                                  'aspects':[{'id':k,'title':v[0],'question':v[1]} for k,v in ASPECTS.items()]});return
                if route.startswith('/api/owner/'):
                    if not self.owner():self.error(403,'owner_key_required');return
                    if route=='/api/owner/summary':self.send(200,store.summary());return
                    rows=store.rows()
                    if route=='/api/owner/export.json':
                        self.send(200,{'schema_version':1,'exported_utc':datetime.now(timezone.utc).isoformat(),'summary':store.summary(),'responses':rows},headers={'Content-Disposition':'attachment; filename="strokesense-feedback.json"'});return
                    if route=='/api/owner/export.csv':
                        fields=['reviewer_id','role','experience','clip_id','analysis_version','aspect_id','usefulness','accuracy','accuracy_reason','timestamp_seconds','comment','created_utc','updated_utc']
                        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
                        for row in rows:
                            safe={k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()}
                            writer.writerow(safe)
                        self.send(200,out.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="strokesense-feedback.csv"'});return
                    self.error(404,'not_found');return
                session = self.session()
                if not session:self.error(401,'begin_review_first');return
                if route=='/api/responses':
                    q=parse_qs(parsed.query,strict_parsing=True,max_num_fields=1)
                    cid=q.get('clip',[''])[0]
                    if cid not in clips: self.error(404,'clip_not_found');return
                    self.send(200,{'responses':store.responses(session['reviewer_id'],cid)});return
                parts=route.strip('/').split('/')
                if len(parts)==3 and parts[0]=='asset' and not parsed.query:
                    cid,kind=parts[1:]
                    if cid not in clips or kind not in ('video','poster','report','annotated') or not clips[cid].get(kind):
                        self.error(404,'asset_not_found');return
                    path=_path(root,clips[cid][kind]);self.media(path, kind);return
                self.error(404,'not_found')
            except (ValueError,KeyError,TypeError):self.error(400,'invalid_request')
            except (BrokenPipeError,ConnectionResetError): pass
            except OSError:self.error(503,'local_file_unavailable')
        def media(self,path,kind):
            total=path.stat().st_size;start,end=0,total-1;code=200
            raw=self.headers.get('Range')
            if raw:
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',raw)
                if not m or not any(m.groups()):self.send(416,b'',headers={'Content-Range':f'bytes */{total}'});return
                a,b=m.groups()
                if a:start=int(a);end=min(int(b),end) if b else end
                else:start=max(0,total-int(b))
                if start>=total or start>end:self.send(416,b'',headers={'Content-Range':f'bytes */{total}'});return
                code=206
            self.send_response(code)
            self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            if kind=='report':self.send_header('Content-Security-Policy',"sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'self'")
            if code==206:self.send_header('Content-Range',f'bytes {start}-{end}/{total}')
            self.end_headers()
            if self.command=='HEAD':return
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    data=f.read(min(65536,remaining))
                    if not data:break
                    self.wfile.write(data);remaining-=len(data)
        def do_POST(self):
            if not self.trusted() or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),csrf):
                self.error(403,'same_origin_and_csrf_required');return
            try:
                lengths=self.headers.get_all('Content-Length') or []
                if len(lengths)!=1 or not lengths[0].isdigit() or self.headers.get_all('Transfer-Encoding'):
                    self.error(400,'invalid_body_length');return
                size=int(lengths[0])
                if not 0<size<=MAX_BODY:self.error(413,'request_too_large');return
                if self.headers.get_content_type()!='application/json':self.error(415,'json_required');return
                self.connection.settimeout(5);raw=self.rfile.read(size)
                if len(raw)!=size:self.error(400,'incomplete_body');return
                data=json.loads(raw)
                route=urlsplit(self.path).path
                if route=='/api/session':
                    if set(data)!={'consent','role','experience'}:raise ValueError('invalid_session_fields')
                    token=store.enroll(data['role'],data['experience'],data['consent'])
                    self.send(201,store.session(token),headers={'Set-Cookie':f'ss_review={token}; HttpOnly; SameSite=Strict; Path=/'});return
                s=self.session()
                if not s:self.error(401,'begin_review_first');return
                if route=='/api/reviews':
                    cid=data.get('clip_id')
                    if cid not in clips:raise ValueError('invalid_clip')
                    row=validate_review(data,clips[cid]);store.save(s['reviewer_id'],row)
                    self.send(200,{'saved':True,'response':row});return
                if route in ('/api/withdraw','/api/end-session'):
                    if data!={}:raise ValueError('invalid_fields')
                    if route=='/api/withdraw':store.withdraw(s['reviewer_id'])
                    self.send(200,{'done':True},headers={'Set-Cookie':'ss_review=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/'});return
                self.error(404,'not_found')
            except (ValueError,KeyError,TypeError) as e:
                known=str(e)
                self.error(422,known if re.fullmatch('[a-z0-9_]{1,60}',known) else 'invalid_feedback')
            except (TimeoutError,BrokenPipeError,ConnectionResetError):pass
            except sqlite3.Error:self.error(503,'feedback_storage_unavailable')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True;server.owner_key=owner;server.store=store
    return server


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pack',type=Path,required=True);p.add_argument('--port',type=int,default=8767)
    args=p.parse_args(argv)
    with create_server(args.pack,port=args.port) as server:
        port=server.server_address[1]
        print(f'Rower review: http://127.0.0.1:{port}/',flush=True)
        print(f'Owner dashboard (keep private): http://127.0.0.1:{port}/#owner={server.owner_key}',flush=True)
        print('Local supervised study only; no public hosting, model download or cloud upload.',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
    return 0

if __name__=='__main__':raise SystemExit(main())
