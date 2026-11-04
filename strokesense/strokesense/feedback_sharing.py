"""Short-lived reviewer invitations and asset-readiness checks, not model validation."""
from __future__ import annotations
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import time
from .feedback import load_catalog, _path

TTL = 7 * 86400


def _signature(owner, code, origin, expiry, nonce):
    message = f'reviewer-invitation-v1:{origin}:{code}:{expiry}:{nonce}'
    return hmac.new(owner.encode(), message.encode(), hashlib.sha256).hexdigest()


def mint_invitation(owner, code, origin):
    expiry = int(time.time()) + TTL
    nonce = secrets.token_hex(16)
    signature = _signature(owner, code, origin, expiry, nonce)
    return f'v1.{expiry}.{nonce}.{signature}', expiry


def verify_invitation(token, owner, code, origin):
    if not isinstance(token, str) or not re.fullmatch(r'v1\.[0-9]{10}\.[a-f0-9]{32}\.[a-f0-9]{64}', token):
        return None
    _, expiry, nonce, signature = token.split('.')
    now = int(time.time())
    if not now < int(expiry) <= now + TTL + 60:
        return None
    expected = _signature(owner, code, origin, int(expiry), nonce)
    return int(expiry) if hmac.compare_digest(signature, expected) else None


def study_readiness(root, expected, catalog_digest=None):
    """Count usable links; do NOT call this accuracy or coach validation."""
    root = Path(root)
    result = {'ready': False, 'expected_clips': expected, 'clip_count': 0,
              'report_count': 0, 'missing': [], 'limits': 'File availability only; not model accuracy or live-host verification.'}
    try:
        path = root / 'catalog.json'
        catalog = load_catalog(path)
        if catalog_digest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != catalog_digest:
            result['error'] = 'catalog_changed_restart_service'
            return result
        result['clip_count'] = len(catalog['clips'])
        for clip in catalog['clips']:
            missing = []
            required = ['video', 'poster', 'report']
            # An honest diagnostic has no generated overlay. A declared overlay
            # or a provisional analysis must still provide its actual media.
            if clip.get('annotated') or clip['analysis'].get('status') not in ('unavailable', 'failed', 'not_run'):
                required.append('annotated')
            for kind in required:
                name = clip.get(kind)
                asset = _path(root, name) if name else None
                if asset is None or not asset.is_file() or asset.stat().st_size == 0:
                    missing.append(kind)
                elif kind == 'report':
                    result['report_count'] += 1
            if missing:
                result['missing'].append({'clip_id': clip['id'], 'assets': missing})
        result['ready'] = result['clip_count'] == expected and not result['missing']
        if not result['ready']:
            result['error'] = 'library_incomplete'
    except (ValueError, KeyError, TypeError, OSError):
        result['error'] = 'study_not_available'
    return result
