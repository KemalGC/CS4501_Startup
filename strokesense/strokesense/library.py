"""Library-enabled local launcher; reuses the existing analysis HTTP server.

Run ``python -m strokesense.library``. Removal is explicit local administration,
not new permission to analyze. Original external files and generated report
files are preserved; removed job URLs stay invalid even after reimport.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hmac
import html
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from . import web
from .jobs import JobQueue
from .registry import DEFAULT_DB, _stream_sha256, list_clips

_CLIP_ID = re.compile(r"[0-9a-f]{64}\Z")
_MANAGED_NAME = re.compile(r"[0-9a-f]{32}\.(?:mp4|mov|mkv|avi|webm)\Z")
_MESSAGES = {
    'active_jobs': (409, 'This clip has queued or running analysis. Let it finish before removing it.'),
    'source_changed': (409, 'The saved upload changed or is not a regular file. Nothing was removed.'),
    'missing_clip': (404, 'This library entry no longer exists. Refresh the library.'),
    'storage_unavailable': (503, 'Local storage is unavailable. Nothing was confirmed removed; retry after checking the local files.'),
}


class RemovalError(ValueError):
    """A fixed public reason, never an internal path or exception message."""


def remove_saved_clip(jobs: JobQueue, clip_id: str, upload_dir: Path) -> dict:
    """Atomically remove registry/job rows; quarantine only a verified owned copy.

    The queue lock serializes this operation with same-process submissions.
    SQLite locks protect the attached databases. The supported deployment is
    one server/worker process, as in JobQueue. Do not run two servers on one DB.
    A crash between rename and commit can leave a private .removing file for
    manual recovery; filesystem and SQLite cannot form one atomic transaction.
    """
    if not isinstance(clip_id, str) or not _CLIP_ID.fullmatch(clip_id):
        raise ValueError('invalid_clip_id')
    uploads = Path(upload_dir).expanduser().resolve()
    if not jobs._registry_db.is_file():
        raise RemovalError('missing_clip')
    source = quarantine = None
    committed = False
    with jobs._mutex:
        with closing(jobs._connection()) as conn:
            try:
                conn.execute('ATTACH DATABASE ? AS registry', (str(jobs._registry_db),))
                # Cross-database atomic commits require rollback journals, not WAL.
                for schema in ('main', 'registry'):
                    mode = conn.execute(f'PRAGMA {schema}.journal_mode').fetchone()[0]
                    if mode not in ('delete', 'truncate', 'persist'):
                        raise RemovalError('storage_unavailable')
                conn.execute('BEGIN IMMEDIATE')
                clip = conn.execute('SELECT * FROM registry.clips WHERE clip_id=?',
                                    (clip_id,)).fetchone()
                if clip is None:
                    raise RemovalError('missing_clip')
                rows = conn.execute('SELECT job_id,status FROM jobs WHERE clip_id=?',
                                    (clip_id,)).fetchall()
                if any(row['status'] in ('queued', 'running') or
                       (jobs._futures.get(row['job_id']) is not None and
                        not jobs._futures[row['job_id']].done()) for row in rows):
                    raise RemovalError('active_jobs')
                candidate = Path(clip['source_path'])
                # Never infer ownership from a filename alone or follow symlinks.
                if candidate.parent == uploads and _MANAGED_NAME.fullmatch(candidate.name):
                    if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
                        raise RemovalError('source_changed')
                    if candidate.exists():
                        if (not candidate.is_file() or candidate.resolve() != candidate
                                or _stream_sha256(candidate) != clip['sha256']):
                            raise RemovalError('source_changed')
                        source = candidate
                        quarantine = uploads / ('.' + uuid4().hex + '.removing')
                        os.replace(source, quarantine)
                conn.execute('DELETE FROM jobs WHERE clip_id=?', (clip_id,))
                conn.execute('DELETE FROM registry.clips WHERE clip_id=?', (clip_id,))
                conn.commit()
                committed = True
                for row in rows:
                    jobs._futures.pop(row['job_id'], None)
            except Exception:
                conn.rollback()
                if quarantine is not None and not committed and quarantine.exists():
                    os.replace(quarantine, source)
                raise
    cleanup_pending = False
    if quarantine is not None:
        try:
            quarantine.unlink()
        except OSError:
            # Records are already removed; do not falsely claim file deletion.
            cleanup_pending = True
    return {'removed_jobs': len(rows), 'upload_deleted': quarantine is not None and not cleanup_pending,
            'cleanup_pending': cleanup_pending}


def create_server(jobs: JobQueue, *, registry_db, host='127.0.0.1', port=0,
                  upload_dir=None):
    """Extend, rather than replace, the existing upload/job/evidence handlers."""
    registry = Path(registry_db).expanduser().resolve()
    if registry != jobs._registry_db:
        raise ValueError('registry must match the job worker')
    uploads = Path(upload_dir if upload_dir is not None else
                   jobs._results_root.parent / 'uploads').expanduser().resolve()
    server = web.create_server(jobs, registry_db=registry, host=host, port=port,
                               upload_dir=uploads)
    base = server.RequestHandlerClass

    class LibraryHandler(base):
        def _send(self, code, data, **kwargs):
            # Only the fixed application navigation, never report or API content.
            if (kwargs.get('csp') != web._REPORT_CSP
                    and b'<nav aria-label="Primary navigation">' in data):
                data = data.replace(b'</nav>', b'<a href="/library">Manage library</a></nav>', 1)
            return super()._send(code, data, **kwargs)

        def _library_error(self, reason):
            status, message = _MESSAGES.get(reason, _MESSAGES['storage_unavailable'])
            self._send(status, web._document('Library action unavailable',
                '<p role="alert">' + html.escape(message) + '</p>'
                '<p><a href="/library">Back to library</a></p>'))

        def _library_get(self, route, query):
            try:
                params = parse_qs(query, keep_blank_values=True, strict_parsing=True,
                                  max_num_fields=2)
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError('invalid_query')
                if route == '/library/remove':
                    if set(params) != {'clip'} or not _CLIP_ID.fullmatch(params['clip'][0]):
                        raise ValueError('invalid_query')
                    clip = next((c for c in list_clips(registry) if c['clip_id'] == params['clip'][0]), None)
                    if clip is None:
                        self._library_error('missing_clip'); return
                    cid = clip['clip_id']
                    body = (f'<h2>Remove clip {cid[:12]}?</h2>'
                        '<p>This removes its library entry, linked analysis history and the '
                        'app-owned uploaded copy, if present. External original videos are '
                        '<strong>not deleted</strong>. Generated report/video files remain on disk, '
                        'but their old web links will no longer work.</p>'
                        '<p>Removal does not grant permission. Import again only when you have '
                        'current permission and provide a truthful permission source.</p>'
                        '<form method="post" action="/library/remove">'
                        f'<input type="hidden" name="clip_id" value="{cid}">'
                        f'<input type="hidden" name="csrf" value="{html.escape(server.csrf_token, quote=True)}">'
                        '<label><input type="checkbox" name="confirm" value="remove" required> '
                        'I understand and want to remove this saved entry and its analysis history.</label>'
                        '<button type="submit">Remove saved clip</button> '
                        '<a href="/library">Cancel</a></form>')
                    self._send(200, web._document('Confirm removal', body)); return
                if set(params) - {'removed', 'cleanup', 'page'}:
                    raise ValueError('invalid_query')
                for name in ('removed', 'cleanup'):
                    if name in params and params[name] != ['1']:
                        raise ValueError('invalid_query')
                raw_page = params.get('page', ['1'])[0]
                if not re.fullmatch(r'[1-9][0-9]{0,5}', raw_page):
                    raise ValueError('invalid_query')
                page = int(raw_page)
                clips = sorted(list_clips(registry), key=lambda c: (c['created_utc'], c['clip_id']), reverse=True)
                selected = clips[(page-1)*50:page*50]
                body = '<p>All saved entries, including blocked clips. Permission controls analysis and preview, not your ability to manage local records.</p>'
                if 'removed' in params:
                    body += '<p role="status">The saved entry and linked analysis history were removed.</p>'
                if 'cleanup' in params:
                    body += '<p role="alert">The entry is removed, but its quarantined upload could not be erased. A private .removing file remains in your uploads directory.</p>'
                body += '<p><a class="button" href="/#upload-clip">Import a video</a></p>'
                if not clips:
                    body += '<h2>Your library is empty</h2><p>Import a recording to get started.</p>'
                for clip in selected:
                    cid = clip['clip_id']
                    if not _CLIP_ID.fullmatch(cid):
                        continue
                    permission = {'granted': 'Granted', 'denied': 'Denied', 'unverified': 'Unverified'}.get(clip['permission'], 'Unknown')
                    body += (f'<section class="history-card" aria-label="Clip {cid[:12]}">'
                        f'<h2>Clip {cid[:12]}</h2><p>Permission: <strong>{permission}</strong> · '
                        f'{clip["size_bytes"]/1024**2:.1f} MiB</p>'
                        f'<p>Imported: {html.escape(clip["created_utc"])}<br>'
                        f'Viewpoint: {html.escape(str(clip.get("camera") or "unspecified"))}</p>')
                    if clip['permission'] == 'granted':
                        body += f'<p><a href="/select?clip={cid}">Choose rowers</a></p>'
                    else:
                        body += '<p>Preview and analysis are blocked. This entry can still be removed.</p>'
                    body += f'<p><a href="/library/remove?clip={cid}">Remove from library…</a></p></section>'
                body += f'<p>Page {page} · {len(clips)} saved entries</p>'
                if page > 1:
                    body += f'<a href="/library?page={page-1}">Previous</a> '
                if page*50 < len(clips):
                    body += f'<a href="/library?page={page+1}">Next</a>'
                self._send(200, web._document('Manage video library', body))
            except (ValueError, TypeError):
                self._error(400)
            except Exception:
                self._library_error('storage_unavailable')

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path not in ('/library', '/library/remove'):
                return super().do_GET()
            if not self._trusted_request():
                self._error(403); return
            self._library_get(parsed.path, parsed.query)

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path != '/library/remove':
                return super().do_POST()
            if not self._trusted_request():
                self._error(403); return
            lengths = self.headers.get_all('Content-Length') or []
            if (parsed.query or len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,8}', lengths[0])
                    or self.headers.get_all('Transfer-Encoding')):
                self._error(400); return
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                self._error(415); return
            length = int(lengths[0])
            if not 0 < length <= 4096:
                self._error(413 if length > 4096 else 400); return
            try:
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._error(400); return
                fields = parse_qs(raw.decode('utf-8'), keep_blank_values=True,
                                  strict_parsing=True, max_num_fields=3)
                if set(fields) != {'csrf', 'clip_id', 'confirm'} or any(len(v) != 1 for v in fields.values()):
                    self._error(400); return
                if not hmac.compare_digest(fields['csrf'][0].encode(), server.csrf_token.encode()):
                    self._error(403); return
                if not _CLIP_ID.fullmatch(fields['clip_id'][0]):
                    self._error(400); return
                if fields['confirm'] != ['remove']:
                    self._error(422); return
                result = remove_saved_clip(jobs, fields['clip_id'][0], uploads)
            except RemovalError as exc:
                self._library_error(str(exc)); return
            except (ValueError, UnicodeError, TimeoutError):
                self._error(400); return
            except Exception:
                self._library_error('storage_unavailable'); return
            location = '/library?removed=1' + ('&cleanup=1' if result['cleanup_pending'] else '')
            self._send(303, b'', location=location)

    server.RequestHandlerClass = LibraryHandler
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='StrokeSense with local library management')
    root = Path(__file__).resolve().parents[1] / 'results'
    parser.add_argument('--registry-db', default=str(DEFAULT_DB))
    parser.add_argument('--jobs-db', default=str(root / 'analysis_jobs.sqlite3'))
    parser.add_argument('--results', default=str(root / 'jobs'))
    parser.add_argument('--uploads', default=str(root / 'uploads'))
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    with JobQueue(registry_db=args.registry_db, job_db=args.jobs_db, results_root=args.results) as jobs:
        with create_server(jobs, registry_db=args.registry_db, upload_dir=args.uploads, port=args.port) as server:
            address = f'http://127.0.0.1:{server.server_address[1]}'
            print(f'Local StrokeSense: {address}/', flush=True)
            print('Upload mode: streaming-150MiB-v4; library-removal-v1', flush=True)
            print(f'Manage all saved entries: {address}/library', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
