"""Offline, private SQLite index for existing local video clips.

Registration never copies, uploads, decodes or runs inference. A permission
value records the operator's claim; it is not independent consent validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sqlite3
import sys

DEFAULT_DB = Path(__file__).resolve().parents[1] / "results" / "video_registry.sqlite3"
PERMISSIONS = ("unverified", "granted", "denied")
SPLITS = ("unassigned", "development", "heldout")


class RegistryError(ValueError):
    """Invalid registry operation that must not create or modify an entry."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    source_path TEXT NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    permission TEXT NOT NULL CHECK(permission IN ('unverified','granted','denied')),
    provenance TEXT,
    group_id TEXT,
    split TEXT NOT NULL CHECK(split IN ('unassigned','development','heldout')),
    camera TEXT,
    fps REAL,
    annotation_version TEXT,
    review_status TEXT NOT NULL,
    created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_group ON clips(group_id, split);
"""
_VISIBLE = (
    "clip_id", "sha256", "size_bytes", "permission", "group_id", "split",
    "camera", "fps", "annotation_version", "review_status", "created_utc",
)


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signature(stat) -> tuple:
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
            getattr(stat, "st_dev", 0), getattr(stat, "st_ino", 0))


def _connect(db_path: str | Path, *, create: bool) -> sqlite3.Connection | None:
    db = Path(db_path).expanduser().resolve()
    if not create and not db.is_file():
        return None
    if create:
        db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    conn = sqlite3.connect(str(db), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _view(row: sqlite3.Row, *, show_paths: bool = False) -> dict:
    result = {field: row[field] for field in _VISIBLE}
    if show_paths:
        result["source_path"] = row["source_path"]
    return result


def register_clip(
    video: str | Path, db_path: str | Path = DEFAULT_DB, *,
    permission: str | None = None, provenance: str | None = None,
    group_id: str | None = None, split: str = "unassigned",
    camera: str | None = None, fps: float | None = None,
) -> tuple[dict, bool]:
    """Return (public record, newly created). Duplicate metadata is immutable."""
    if permission is not None and permission not in PERMISSIONS:
        raise RegistryError("unknown permission status")
    if split not in SPLITS:
        raise RegistryError("unknown evaluation split")
    if provenance is not None and not isinstance(provenance, str):
        raise RegistryError("provenance must be text")
    provenance = provenance.strip() if provenance is not None else None
    if group_id is not None:
        if not isinstance(group_id, str) or not group_id.strip():
            raise RegistryError("recording group must be nonempty text")
        group_id = group_id.strip()
    if split != "unassigned" and group_id is None:
        raise RegistryError("evaluation split requires a recording group")
    if permission == "granted" and not provenance:
        raise RegistryError("granted permission requires explicit provenance")
    if fps is not None:
        try:
            fps = float(fps)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RegistryError("fps must be finite and positive") from exc
        if not math.isfinite(fps) or fps <= 0:
            raise RegistryError("fps must be finite and positive")
    if camera is not None and not isinstance(camera, str):
        raise RegistryError("camera must be text")

    path = Path(video).expanduser().resolve(strict=True)
    if not path.is_file():
        raise RegistryError("source must be a regular local file")
    before = path.stat()
    if before.st_size <= 0:
        raise RegistryError("source is empty")
    digest = _stream_sha256(path)
    if _signature(before) != _signature(path.stat()):
        raise RegistryError("source changed while hashing; retry")

    conn = _connect(db_path, create=True)
    assert conn is not None
    try:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM clips WHERE clip_id = ?", (digest,)).fetchone()
        if previous is not None:
            proposed = {
                "permission": permission, "provenance": provenance,
                "group_id": group_id, "camera": camera, "fps": fps,
            }
            for key, value in proposed.items():
                if value is not None and previous[key] != value:
                    raise RegistryError("duplicate content conflicts on " + key)
            if split != "unassigned" and split != previous["split"]:
                raise RegistryError("duplicate content conflicts on split")
            result = _view(previous)
            conn.commit()
            return result, False

        if group_id is not None and split != "unassigned":
            conflict = conn.execute(
                "SELECT 1 FROM clips WHERE group_id = ? "
                "AND split NOT IN ('unassigned', ?) LIMIT 1",
                (group_id, split),
            ).fetchone()
            if conflict is not None:
                raise RegistryError("recording group is assigned to a different split")
        conn.execute(
            "INSERT INTO clips (clip_id, sha256, size_bytes, source_path, "
            "source_mtime_ns, permission, provenance, group_id, split, camera, "
            "fps, annotation_version, review_status, created_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                digest, digest, before.st_size, str(path), before.st_mtime_ns,
                permission if permission is not None else "unverified",
                provenance, group_id, split, camera, fps, None, "unreviewed",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        row = conn.execute("SELECT * FROM clips WHERE clip_id = ?", (digest,)).fetchone()
        result = _view(row)
        conn.commit()
        return result, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_clips(db_path: str | Path = DEFAULT_DB, *, show_paths: bool = False) -> list[dict]:
    """List safe metadata; paths are only shown on explicit request."""
    conn = _connect(db_path, create=False)
    if conn is None:
        return []
    try:
        return [_view(row, show_paths=show_paths) for row in conn.execute(
            "SELECT * FROM clips ORDER BY created_utc, clip_id"
        ).fetchall()]
    finally:
        conn.close()



def analysis_permission_granted(
    clip_id: str, db_path: str | Path = DEFAULT_DB,
) -> bool:
    """Check current local operator permission without creating a database."""
    if not isinstance(clip_id, str):
        return False
    conn = _connect(db_path, create=False)
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT permission FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        return row is not None and row["permission"] == "granted"
    finally:
        conn.close()


def revoke_clip(
    clip_id: str, db_path: str | Path = DEFAULT_DB,
) -> dict:
    """Permanently deny analysis of a registered clip (no file deletion).

    This changes only the local permission claim; prior reports are retained.
    BEGIN IMMEDIATE serializes concurrent permission updates.
    """
    if not isinstance(clip_id, str) or not re.fullmatch(r"[0-9a-f]{64}", clip_id):
        raise RegistryError("invalid clip id")
    conn = _connect(db_path, create=False)
    if conn is None:
        raise RegistryError("clip not found")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            raise RegistryError("clip not found")
        if row["permission"] != "denied":
            conn.execute(
                "UPDATE clips SET permission = 'denied' WHERE clip_id = ?",
                (clip_id,),
            )
            row = conn.execute(
                "SELECT * FROM clips WHERE clip_id = ?", (clip_id,)
            ).fetchone()
        result = _view(row)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register or list local clips without uploading")
    sub = parser.add_subparsers(dest="operation", required=True)
    add = sub.add_parser("import", help="Index existing local video with SHA-256")
    add.add_argument("video")
    add.add_argument("--db", default=str(DEFAULT_DB))
    add.add_argument("--permission", choices=PERMISSIONS, default=None)
    add.add_argument("--provenance")
    add.add_argument("--group", dest="group_id")
    add.add_argument("--split", choices=SPLITS, default="unassigned")
    add.add_argument("--camera")
    add.add_argument("--fps", type=float)
    listing = sub.add_parser("list", help="List indexed clips")
    listing.add_argument("--db", default=str(DEFAULT_DB))
    listing.add_argument("--show-path", action="store_true", help="Reveal private source paths")
    revoke = sub.add_parser("revoke", help="Deny analysis of a registered clip")
    revoke.add_argument("clip_id", help="SHA-256 clip ID (not a file path)")
    revoke.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args(argv)
    try:
        if args.operation == "import":
            record, created = register_clip(
                args.video, args.db, permission=args.permission,
                provenance=args.provenance, group_id=args.group_id,
                split=args.split, camera=args.camera, fps=args.fps,
            )
            print(json.dumps({"record": record, "created": created}, sort_keys=True))
        elif args.operation == "revoke":
            record = revoke_clip(args.clip_id, args.db)
            print(json.dumps({"record": record}, sort_keys=True))
        else:
            print(json.dumps(list_clips(args.db, show_paths=args.show_path), sort_keys=True))
    except RegistryError as exc:
        print("Registry error: " + str(exc), file=sys.stderr)
        return 2
    except (OSError, sqlite3.DatabaseError):
        print("Registry error: storage unavailable", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
