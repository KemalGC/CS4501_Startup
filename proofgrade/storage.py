"""Opt-in anonymous outcome storage. No submitted equations or model text."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sqlite3


class AttemptStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, problem_id TEXT NOT NULL,
                    status TEXT NOT NULL, first_error_step INTEGER, hint_status TEXT NOT NULL,
                    provider_mode TEXT NOT NULL, generation_attempts INTEGER NOT NULL,
                    rejected_candidates INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
                    previous_attempt_id TEXT REFERENCES attempts(id),
                    corrected_previous_step INTEGER, rating INTEGER CHECK(rating BETWEEN 1 AND 5)
                )
            """)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, problem_id, feedback, mode, latency_ms, step_count, previous_attempt_id=None):
        attempt_id = secrets.token_urlsafe(24)
        corrected = None
        with self.connection() as connection:
            if previous_attempt_id:
                previous = connection.execute("SELECT * FROM attempts WHERE id=?", (previous_attempt_id,)).fetchone()
                if previous is None or previous["problem_id"] != problem_id or previous["provider_mode"] != mode:
                    raise ValueError("Previous attempt must belong to this problem and hint mode.")
                index = previous["first_error_step"]
                if index is not None and previous["hint_status"] == "verified":
                    check = feedback.check
                    passed_step = (check.status in ("correct", "incomplete")
                                   or (check.first_error_step is not None and check.first_error_step > index)
                                   or (check.unsupported_step is not None and check.unsupported_step > index))
                    corrected = int(step_count >= index and passed_step)
            connection.execute("""
                INSERT INTO attempts
                (id,created_at,problem_id,status,first_error_step,hint_status,provider_mode,
                 generation_attempts,rejected_candidates,latency_ms,previous_attempt_id,corrected_previous_step)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (attempt_id, datetime.now(timezone.utc).isoformat(), problem_id,
                  feedback.check.status, feedback.check.first_error_step, feedback.hint_status, mode,
                  feedback.attempts, feedback.rejected_candidates, latency_ms, previous_attempt_id, corrected))
        return attempt_id

    def rate(self, attempt_id, rating):
        with self.connection() as connection:
            cursor = connection.execute("UPDATE attempts SET rating=? WHERE id=? AND hint_status='verified'", (rating, attempt_id))
        return cursor.rowcount == 1
