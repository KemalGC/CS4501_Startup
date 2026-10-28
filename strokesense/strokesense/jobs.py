"""Bounded, private local analysis jobs for a future upload/results interface.

This is a single-process worker foundation, not a distributed queue or public
HTTP service. Persisted status is safe to display; raw source paths and internal
error messages never leave the private registry and worker process.
"""
from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from .registry import _stream_sha256, list_clips, analysis_permission_granted
from .media import UndecodableMediaError, probe_decodable_video

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
    created_utc TEXT NOT NULL,
    started_utc TEXT,
    finished_utc TEXT,
    report_path TEXT,
    report_sha256 TEXT,
    metrics_sha256 TEXT,
    video_path TEXT,
    video_sha256 TEXT,
    error_code TEXT,
    coaching_state TEXT NOT NULL DEFAULT 'withheld'
        CHECK(coaching_state IN ('withheld','released'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_utc);
"""
_PUBLIC_COLUMNS = (
    "job_id", "clip_id", "status", "created_utc", "started_utc",
    "finished_utc", "report_path", "error_code", "coaching_state",
)


MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_METRICS_BYTES = 16 * 1024 * 1024
MAX_MEDIA_BYTES = 64 * 1024 * 1024  # conservative local playback cap


class _ResultTooLarge(ValueError):
    """Generated artifacts must fit the local browser's actual read limits."""


def _bounded_sha256(path: Path, max_bytes: int) -> str:
    """Digest at most limit + 1 bytes; do not trust stale stat metadata."""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise _ResultTooLarge()
            digest.update(chunk)
    return digest.hexdigest()


class JobError(ValueError):
    """Safe error code for an invalid or full local job request."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)


def _matches_registered_source(video: Path, expected_sha: str) -> bool:
    """Best-effort streamed source integrity check; never disclose its path."""
    try:
        return video.is_file() and _stream_sha256(video) == expected_sha
    except OSError:
        return False


def _default_analyze(video: Path, *, out_dir: Path):
    # Only the production analyzer performs decoding; injected offline
    # analyze_fn fixtures deliberately have no dependency on real video files.
    if not probe_decodable_video(video):
        raise UndecodableMediaError("invalid_media")
    from .cli import analyse_video  # Heavy pose dependencies load only on execution.
    return analyse_video(video, out_dir=out_dir)


class JobQueue:
    """Bounded local worker and durable report pointers, never source paths.

    The permission flag comes from the operator's registry declaration; this
    is not evidence of externally verified consent.
    """

    def __init__(
        self, *, registry_db, job_db, results_root,
        analyze_fn=None, max_pending: int = 3,
    ):
        if type(max_pending) is not int or not 1 <= max_pending <= 32:
            raise ValueError("max_pending must be an integer in [1,32]")
        self._registry_db = Path(registry_db).expanduser().resolve()
        self._job_db = Path(job_db).expanduser().resolve()
        self._results_root = Path(results_root).expanduser().resolve()
        self._results_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _prepare_db(self._job_db)
        self._analyze_fn = analyze_fn or _default_analyze
        self._permits = BoundedSemaphore(max_pending)
        self._mutex = Lock()
        self._closed = False
        self._futures = {}
        with closing(self._connection()) as conn, conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise ValueError("unsupported newer jobs schema")
            conn.executescript(_SCHEMA)
            if version < 5:
                # Version 5: bind optional media bytes to the same job; keep
                # earlier v4 report/metrics integrity migration non-destructive.
                # Historical jobs/reports remain intact, but old rows cannot
                # be authenticated on read until a fresh analysis runs.
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute("PRAGMA user_version").fetchone()[0]
                if current > 5:
                    raise ValueError("unsupported newer jobs schema")
                columns = {col["name"] for col in
                           conn.execute("PRAGMA table_info(jobs)")}
                if "coaching_state" not in columns:
                    conn.execute(
                        "ALTER TABLE jobs ADD COLUMN coaching_state TEXT "
                        "NOT NULL DEFAULT 'withheld' "
                        "CHECK(coaching_state IN ('withheld','released'))"
                    )
                if "report_sha256" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN report_sha256 TEXT")
                if "metrics_sha256" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN metrics_sha256 TEXT")
                if "video_path" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN video_path TEXT")
                if "video_sha256" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN video_sha256 TEXT")
                conn.execute("PRAGMA user_version = 5")
                conn.commit()
            columns = {col["name"] for col in
                       conn.execute("PRAGMA table_info(jobs)")}
            if not {"coaching_state", "report_sha256",
                    "metrics_sha256", "video_path", "video_sha256"}.issubset(columns):
                raise ValueError("incomplete jobs schema")
            # No in-memory worker from a prior process can complete these jobs.
            conn.execute(
                "UPDATE jobs SET status='failed', error_code='interrupted', "
                "finished_utc=? WHERE status IN ('queued','running')",
                (_utc(),),
            )
            conn.commit()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="strokesense-local-job"
        )

    def _connection(self):
        conn = sqlite3.connect(str(self._job_db), timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _write(self, job_id: str, status: str, **changes) -> None:
        fields = ["status = ?"]
        values = [status]
        for column in ("started_utc", "finished_utc", "report_path",
                       "report_sha256", "metrics_sha256", "video_path",
                       "video_sha256", "error_code"):
            if column in changes:
                fields.append(column + " = ?")
                values.append(changes[column])
        values.append(job_id)
        with closing(self._connection()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET " + ", ".join(fields) + " WHERE job_id = ?",
                values,
            )

    def get(self, job_id: str):
        if not isinstance(job_id, str) or not job_id:
            return None
        with closing(self._connection()) as conn:
            row = conn.execute(
                "SELECT " + ", ".join(_PUBLIC_COLUMNS)
                + " FROM jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
        return {key: row[key] for key in _PUBLIC_COLUMNS} if row is not None else None

    def report_sha256(self, job_id: str) -> str | None:
        """Private digest for the HTTP integrity gate; never in public status."""
        if not isinstance(job_id, str) or not job_id:
            return None
        with closing(self._connection()) as conn:
            row = conn.execute(
                "SELECT report_sha256 FROM jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
        return row["report_sha256"] if row is not None else None

    def metrics_sha256(self, job_id: str) -> str | None:
        """Private digest binding evidence JSON to the completed local job."""
        if not isinstance(job_id, str) or not job_id:
            return None
        with closing(self._connection()) as conn:
            row = conn.execute(
                "SELECT metrics_sha256 FROM jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
        return row["metrics_sha256"] if row is not None else None

    def media_artifact(self, job_id: str) -> tuple[str, str] | None:
        """Private job-bound media location and digest; excluded from API."""
        if not isinstance(job_id, str) or not job_id:
            return None
        with closing(self._connection()) as conn:
            row = conn.execute(
                "SELECT video_path, video_sha256 FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None or not row["video_path"] or not row["video_sha256"]:
            return None
        return row["video_path"], row["video_sha256"]

    def list_recent(self, limit: int = 20) -> list[dict]:
        """Bounded newest-first public status records; never expose private paths."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("history limit must be an integer in [1,100]")
        with closing(self._connection()) as conn:
            rows = conn.execute(
                "SELECT " + ", ".join(_PUBLIC_COLUMNS)
                + " FROM jobs ORDER BY created_utc DESC, job_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{column: row[column] for column in _PUBLIC_COLUMNS}
                for row in rows]

    def submit(self, clip_id: str) -> dict:
        if not isinstance(clip_id, str) or not clip_id:
            raise JobError("invalid_clip_id")
        with self._mutex:
            if self._closed:
                raise JobError("queue_closed")
            if not self._permits.acquire(blocking=False):
                raise JobError("queue_full")
            try:
                # Only lookup the path inside this private service; do not
                # publish or log it in status/error responses.
                clip = next(
                    (rec for rec in list_clips(self._registry_db, show_paths=True)
                     if rec["clip_id"] == clip_id), None
                )
                if clip is None:
                    raise JobError("unregistered_clip")
                if clip.get("permission") != "granted":
                    raise JobError("permission_unverified")

                job_id = uuid4().hex
                created = _utc()
                with closing(self._connection()) as conn, conn:
                    conn.execute(
                        "INSERT INTO jobs (job_id,clip_id,status,created_utc) "
                        "VALUES (?,?,?,?)",
                        (job_id, clip_id, "queued", created),
                    )
                self._futures[job_id] = self._executor.submit(
                    self._run, job_id, clip_id, Path(clip["source_path"]), clip["sha256"]
                )
                return {
                    "job_id": job_id, "clip_id": clip_id, "status": "queued",
                    "created_utc": created, "started_utc": None,
                    "finished_utc": None, "report_path": None, "error_code": None,
                    "coaching_state": "withheld",
                }
            except Exception:
                self._permits.release()
                raise

    def _run(self, job_id: str, clip_id: str, video: Path, expected_sha: str) -> None:
        try:
            self._write(job_id, "running", started_utc=_utc())
            if not analysis_permission_granted(clip_id, self._registry_db):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="permission_revoked")
                return
            if not _matches_registered_source(video, expected_sha):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="source_changed")
                return

            # Even two jobs for the same clip never share reports or caches.
            run_root = self._results_root / job_id
            try:
                run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
            except OSError:
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="output_unavailable")
                return
            try:
                result = self._analyze_fn(video, out_dir=run_root)
            except UndecodableMediaError:
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="invalid_media")
                return
            except Exception:
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="analysis_failed")
                return
            # Permission can be withdrawn while the analyzer is running.
            # Do not release the resulting report after a withdrawal.
            if not analysis_permission_granted(clip_id, self._registry_db):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="permission_revoked")
                return
            # Fail closed if the registered bytes changed while analyzing.
            # The file may still change after this check; immutable ingest
            # is needed for stronger guarantees.
            if not _matches_registered_source(video, expected_sha):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="source_changed")
                return
            if result is None:
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="no_rowing_detected")
                return
            try:
                if not isinstance(result, Mapping):
                    raise ValueError("invalid result")
                report = Path(result["report"]).resolve(strict=True)
                if (not report.is_file() or report.name != "report.html"
                        or not report.is_relative_to(run_root.resolve())):
                    raise ValueError("invalid report")
                relative = report.relative_to(self._results_root).as_posix()
                digest = _bounded_sha256(report, MAX_REPORT_BYTES)
                metrics = report.parent / "metrics.json"
                metrics_digest = None
                if metrics.exists():
                    resolved = metrics.resolve(strict=True)
                    if (not resolved.is_file() or not
                            resolved.is_relative_to(run_root.resolve())):
                        raise ValueError("invalid metrics location")
                    metrics_digest = _bounded_sha256(resolved, MAX_METRICS_BYTES)
                video_relative = media_digest = None
                if result.get("video") is not None:
                    rendered = Path(result["video"]).resolve(strict=True)
                    if (not rendered.is_file() or
                            rendered.suffix.lower() not in (".mp4", ".webm") or
                            not rendered.is_relative_to(run_root.resolve())):
                        raise ValueError("invalid media location")
                    video_relative = rendered.relative_to(
                        self._results_root).as_posix()
                    media_digest = _bounded_sha256(rendered, MAX_MEDIA_BYTES)
            except _ResultTooLarge:
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="result_too_large")
                return
            except (OSError, TypeError, ValueError, KeyError):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="invalid_report_location")
                return
            self._write(job_id, "succeeded", finished_utc=_utc(),
                        report_path=relative, report_sha256=digest,
                        metrics_sha256=metrics_digest,
                        video_path=video_relative, video_sha256=media_digest)
        finally:
            self._permits.release()

    def wait(self, job_id: str, *, timeout: float | None = None) -> dict:
        future = self._futures.get(job_id)
        if future is None:
            raise ValueError("unknown job")
        future.result(timeout=timeout)
        result = self.get(job_id)
        assert result is not None
        return result

    def close(self) -> None:
        with self._mutex:
            self._closed = True
        self._executor.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
