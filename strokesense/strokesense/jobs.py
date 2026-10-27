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
import os
from pathlib import Path
import sqlite3
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from .registry import _stream_sha256, list_clips
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
    error_code TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_utc);
"""
_PUBLIC_COLUMNS = (
    "job_id", "clip_id", "status", "created_utc", "started_utc",
    "finished_utc", "report_path", "error_code",
)


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
            conn.executescript(_SCHEMA)
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
        for column in ("started_utc", "finished_utc", "report_path", "error_code"):
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
                    self._run, job_id, Path(clip["source_path"]), clip["sha256"]
                )
                return {
                    "job_id": job_id, "clip_id": clip_id, "status": "queued",
                    "created_utc": created, "started_utc": None,
                    "finished_utc": None, "report_path": None, "error_code": None,
                }
            except Exception:
                self._permits.release()
                raise

    def _run(self, job_id: str, video: Path, expected_sha: str) -> None:
        try:
            self._write(job_id, "running", started_utc=_utc())
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
            except (OSError, TypeError, ValueError, KeyError):
                self._write(job_id, "failed", finished_utc=_utc(),
                            error_code="invalid_report_location")
                return
            self._write(job_id, "succeeded", finished_utc=_utc(),
                        report_path=relative)
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
