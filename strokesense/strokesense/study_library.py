"""Import already-computed private study outputs into the normal video library.

Saved study analyses have their own records. They are never fabricated queue
successes, and importing them cannot run inference or restore revoked consent.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .jobs import MAX_REPORT_BYTES, MAX_METRICS_BYTES, _bounded_sha256
from .registry import list_clips, register_clip

ID_RE = re.compile(r'[0-9a-f]{32}\Z')
CLIP_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
MAX_SOURCE_BYTES = 150 * 1024 * 1024
_LIMITS = {'report': MAX_REPORT_BYTES, 'metrics': MAX_METRICS_BYTES,
           'annotated': MAX_SOURCE_BYTES, 'poster': 4 * 1024 * 1024}
_SUFFIXES = {'report': {'.html'}, 'metrics': {'.json'},
             'annotated': {'.mp4', '.webm'}, 'poster': {'.jpg', '.jpeg', '.png', '.webp'}}
_VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS library_saved_analyses (
 analysis_id TEXT PRIMARY KEY,
 clip_id TEXT NOT NULL,
 study_clip_id TEXT NOT NULL,
 title TEXT NOT NULL,
 imported_utc TEXT NOT NULL,
 analysis_version TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 analysis_json TEXT NOT NULL,
 provenance_json TEXT NOT NULL,
 artifacts_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_analyses_clip
 ON library_saved_analyses(clip_id, imported_utc);
CREATE INDEX IF NOT EXISTS idx_library_analyses_fingerprint
 ON library_saved_analyses(fingerprint);
'''


class StudyImportError(ValueError):
    """A safe public code, without private file paths."""


class SavedAnalysisError(ValueError):
    """A bounded HTTP status and public reason for unavailable saved output."""
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


def prepare_store(jobs):
    with closing(jobs._connection()) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _file(root, relative, suffixes, limit):
    if not isinstance(relative, str) or not relative or len(relative) > 500:
        raise StudyImportError('invalid_asset_path')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in relative:
        raise StudyImportError('invalid_asset_path')
    candidate = root / rel
    # Reject links even when their current targets happen to be within the pack.
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (candidate, *candidate.parents)):
        raise StudyImportError('linked_asset')
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise StudyImportError('invalid_asset_path')
        if resolved.suffix.lower() not in suffixes:
            raise StudyImportError('unsupported_asset_type')
        size = resolved.stat().st_size
        if not 0 < size <= limit:
            raise StudyImportError('asset_size_invalid')
        digest = _bounded_sha256(resolved, limit)
    except (OSError, ValueError) as exc:
        if isinstance(exc, StudyImportError):
            raise
        raise StudyImportError('asset_unavailable') from exc
    return {'source': resolved, 'sha256': digest, 'size': size}


def _prepare_pack(catalog_path):
    path = Path(catalog_path).expanduser()
    if path.is_dir():
        path = path / 'catalog.json'
    path = path.resolve(strict=True)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise StudyImportError('catalog_too_large')
    try:
        catalog = json.loads(path.read_text('utf-8'))
        clips = catalog['clips']
        if catalog.get('schema_version') != 1 or not isinstance(clips, list) or not 1 <= len(clips) <= 100:
            raise ValueError()
        prepared = []
        seen = set()
        for item in clips:
            sid = item['id']
            title = item['title']
            analysis = item['analysis']
            version = analysis['version']
            duration = item['duration']
            if (not isinstance(sid, str) or not CLIP_RE.fullmatch(sid) or sid in seen
                    or not isinstance(title, str) or not 0 < len(title) <= 200
                    or not isinstance(version, str) or not 0 < len(version) <= 200
                    or type(duration) not in (int, float) or not math.isfinite(duration)
                    or not 0 < duration <= 3600):
                raise ValueError()
            seen.add(sid)
            group_id = item.get('group_id')
            if group_id is not None and (not isinstance(group_id, str) or not group_id.strip() or len(group_id) > 500):
                raise ValueError()
            if len(_json(analysis)) > 128 * 1024:
                raise ValueError()
            window = analysis.get('window')
            if window is not None:
                start, end = window['start'], window['end']
                if (type(start) not in (int, float) or type(end) not in (int, float)
                        or not math.isfinite(start) or not math.isfinite(end)
                        or start < 0 or end <= start):
                    raise ValueError()
            source = _file(path.parent, item['video'], _VIDEO_SUFFIXES, MAX_SOURCE_BYTES)
            artifacts = {name: _file(path.parent, item[name], _SUFFIXES[name], limit)
                         for name, limit in _LIMITS.items() if item.get(name)}
            # Metrics must be actual bounded JSON, not a renamed arbitrary file.
            if 'metrics' in artifacts:
                metrics = json.loads(artifacts['metrics']['source'].read_text('utf-8'))
                if not isinstance(metrics, dict):
                    raise ValueError()
            provenance = {'permission_source': None, 'study_clip_id': sid,
                          'group_id': item.get('group_id'), 'source_sha256': source['sha256'],
                          'study_provenance': item.get('provenance', {}),
                          'duration': duration}
            if len(_json(provenance)) > 128 * 1024:
                raise ValueError()
            fingerprint = hashlib.sha256(_json({
                'source': source['sha256'], 'id': sid, 'title': title,
                'analysis': analysis, 'provenance': provenance,
                'artifacts': {k: v['sha256'] for k, v in artifacts.items()}
            }).encode()).hexdigest()
            prepared.append({'id': sid, 'title': title, 'analysis': analysis,
                             'version': version, 'source': source, 'artifacts': artifacts,
                             'provenance': provenance, 'fingerprint': fingerprint})
        return prepared
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, StudyImportError):
            raise
        raise StudyImportError('invalid_catalog') from exc


def _copy(source, target, expected, limit):
    if target.resolve() != target:
        raise StudyImportError('linked_destination')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.parent.resolve() != target.parent:
        raise StudyImportError('linked_destination')
    digest = hashlib.sha256()
    total = 0
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as handle:
            while chunk := handle.read(min(1024 * 1024, limit - total + 1)):
                total += len(chunk)
                if total > limit:
                    raise StudyImportError('asset_changed_during_import')
                out.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise StudyImportError('asset_changed_during_import')
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _decode(row):
    value = dict(row)
    value['analysis'] = json.loads(value.pop('analysis_json'))
    value['artifacts'] = json.loads(value.pop('artifacts_json'))
    # Never return the private provenance payload to browser renderers.
    value.pop('provenance_json', None)
    return value


def list_saved_analyses(jobs, clip_ids):
    if not clip_ids:
        return {}
    marks = ','.join('?' for _ in clip_ids)
    with closing(jobs._connection()) as conn:
        rows = conn.execute(f'SELECT * FROM library_saved_analyses WHERE clip_id IN ({marks}) '
                            'ORDER BY imported_utc DESC, analysis_id DESC', tuple(clip_ids)).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row['clip_id'], []).append(_decode(row))
    return grouped


def get_saved_analysis(jobs, analysis_id):
    if not isinstance(analysis_id, str) or not ID_RE.fullmatch(analysis_id):
        raise SavedAnalysisError(404, 'Saved analysis not found.')
    with closing(jobs._connection()) as conn:
        row = conn.execute('SELECT * FROM library_saved_analyses WHERE analysis_id=?',
                           (analysis_id,)).fetchone()
    if row is None:
        raise SavedAnalysisError(404, 'Saved analysis not found.')
    return _decode(row)


def checked_source(jobs, saved):
    clip = next((c for c in list_clips(jobs._registry_db, show_paths=True)
                 if c['clip_id'] == saved['clip_id']), None)
    if clip is None:
        raise SavedAnalysisError(404, 'The recording is no longer in the library.')
    if clip['permission'] != 'granted':
        raise SavedAnalysisError(403, 'Permission no longer allows access to this recording or its analysis.')
    source = Path(clip['source_path'])
    try:
        if (source.is_symlink() or source.resolve() != source or not source.is_file()
                or _bounded_sha256(source, MAX_SOURCE_BYTES) != clip['sha256']):
            raise SavedAnalysisError(409, 'The saved recording changed or is unavailable. Its analysis cannot be verified.')
    except (OSError, ValueError) as exc:
        if isinstance(exc, SavedAnalysisError):
            raise
        raise SavedAnalysisError(409, 'The saved recording changed or is unavailable. Its analysis cannot be verified.') from exc
    return source


def _artifact_path(jobs, saved, role):
    asset = saved['artifacts'].get(role)
    if asset is None or role not in _LIMITS:
        raise SavedAnalysisError(404, 'This output was not produced for the saved analysis.')
    relative = Path(asset['path'])
    expected = Path('library_saved') / saved['analysis_id']
    candidate = jobs._results_root / relative
    if (relative.is_absolute() or '..' in relative.parts or relative.parent != expected
            or candidate.is_symlink() or candidate.resolve() != candidate
            or not candidate.is_file()):
        raise SavedAnalysisError(409, 'Saved analysis files are unavailable or changed.')
    return candidate, asset


def read_saved_asset(jobs, saved, role):
    source = checked_source(jobs, saved)
    if role == 'video':
        target, expected, limit = source, saved['clip_id'], MAX_SOURCE_BYTES
    else:
        target, asset = _artifact_path(jobs, saved, role)
        expected, limit = asset['sha256'], _LIMITS[role]
    try:
        with target.open('rb') as handle:
            data = handle.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
            raise SavedAnalysisError(409, 'Saved analysis files are unavailable or changed.')
    except OSError as exc:
        raise SavedAnalysisError(409, 'Saved analysis files are unavailable or changed.') from exc
    return data, target.suffix.lower()


def report_available(jobs, saved):
    """A card checks stored report integrity; source is rechecked on every open."""
    try:
        target, asset = _artifact_path(jobs, saved, 'report')
        return _bounded_sha256(target, MAX_REPORT_BYTES) == asset['sha256']
    except (SavedAnalysisError, OSError, ValueError):
        return False


def import_study_pack(jobs, catalog_path, *, upload_dir, permission_source):
    """Copy reviewed study media and actual saved outputs; return stable IDs.

    Uses existing granted registration when bytes are already registered, and
    never changes its permission/provenance. All referenced files are validated
    before import starts. Repeated unchanged imports reuse intact saved records.
    """
    if not isinstance(permission_source, str) or not permission_source.strip() or len(permission_source) > 2000:
        raise StudyImportError('permission_source_required')
    prepared = _prepare_pack(catalog_path)
    uploads = Path(upload_dir).expanduser().resolve()
    uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
    prepare_store(jobs)
    imported = []
    with jobs._mutex:
        for item in prepared:
            cid = item['source']['sha256']
            clip = next((c for c in list_clips(jobs._registry_db, show_paths=True)
                         if c['clip_id'] == cid), None)
            if clip is not None:
                if clip['permission'] != 'granted':
                    raise StudyImportError('registered_permission_blocked')
                try:
                    checked_source(jobs, {'clip_id': cid})
                except SavedAnalysisError as exc:
                    raise StudyImportError('registered_source_changed') from exc
            with closing(jobs._connection()) as conn:
                rows = conn.execute('SELECT * FROM library_saved_analyses WHERE fingerprint=? '
                                    'ORDER BY imported_utc DESC', (item['fingerprint'],)).fetchall()
            reused = None
            for row in rows:
                saved = _decode(row)
                try:
                    if clip is not None:
                        for role in saved['artifacts']:
                            target, asset = _artifact_path(jobs, saved, role)
                            if _bounded_sha256(target, _LIMITS[role]) != asset['sha256']:
                                raise ValueError()
                        reused = saved
                        break
                except (OSError, ValueError):
                    continue
            if reused is not None:
                imported.append({'analysis_id': reused['analysis_id'], 'clip_id': cid,
                                 'study_clip_id': item['id'], 'reused': True})
                continue
            aid = uuid4().hex
            output = jobs._results_root / 'library_saved' / aid
            assets = {}
            managed_source = None
            try:
                for role, asset in item['artifacts'].items():
                    target = output / (role + asset['source'].suffix.lower())
                    _copy(asset['source'], target, asset['sha256'], _LIMITS[role])
                    assets[role] = {'path': str(target.relative_to(jobs._results_root)),
                                    'sha256': asset['sha256'], 'size': asset['size']}
                if clip is None:
                    managed_source = uploads / (uuid4().hex + item['source']['source'].suffix.lower())
                    _copy(item['source']['source'], managed_source, cid, MAX_SOURCE_BYTES)
                    clip, created = register_clip(managed_source, jobs._registry_db,
                        permission='granted', provenance=permission_source.strip(),
                        group_id=item['provenance']['group_id'])
                    if not created:
                        managed_source.unlink(missing_ok=True)
                        managed_source = None
                provenance = dict(item['provenance'], permission_source=permission_source.strip())
                with closing(jobs._connection()) as conn:
                    conn.execute('INSERT INTO library_saved_analyses VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (aid, cid, item['id'], item['title'], datetime.now(timezone.utc).isoformat(),
                         item['version'], item['fingerprint'], _json(item['analysis']),
                         _json(provenance), _json(assets)))
                    conn.commit()
            except Exception:
                shutil.rmtree(output, ignore_errors=True)
                # Keep a registered source if saving output failed. It remains a
                # real, usable clip; a retry completes the import without regranting.
                if managed_source is not None:
                    registered = any(c['clip_id'] == cid for c in list_clips(jobs._registry_db))
                    if not registered:
                        managed_source.unlink(missing_ok=True)
                raise
            imported.append({'analysis_id': aid, 'clip_id': cid, 'study_clip_id': item['id'], 'reused': False})
    return imported
