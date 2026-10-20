"""Private SQLite teacher workspaces, revocable sessions, and versioned review records."""

from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time


class MissingRecord(Exception):
    pass


class RevisionConflict(Exception):
    pass


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


class TeacherStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS teachers (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES teachers(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES teachers(id), data TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                    student_code TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
                    data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(assignment_id, student_code));
                CREATE TABLE IF NOT EXISTS pages (
                    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, png BLOB NOT NULL, PRIMARY KEY(submission_id, number));
                CREATE TABLE IF NOT EXISTS review_events (
                    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS practice_sets (
                    id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                    data TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS assignment_owner ON assignments(owner);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_teacher(self, username, password):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username) or not 12 <= len(password) <= 128:
            raise ValueError("Use a 3–64 character username and a password of 12–128 characters.")
        salt, owner = secrets.token_hex(16), secrets.token_hex(16)
        with self.connection() as db:
            db.execute("INSERT INTO teachers VALUES (?,?,?,?)",
                       (owner, username, salt, password_hash(password, salt)))
        return owner

    def login(self, username, password):
        with self.connection() as db:
            user = db.execute("SELECT * FROM teachers WHERE username=?", (username,)).fetchone()
            salt = user["salt"] if user else "0" * 32
            match = hmac.compare_digest(password_hash(password, salt), user["hash"] if user else "0" * 64)
            if not user or not match:
                return None
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + 8 * 3600))
            return token

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.connection() as db:
            row = db.execute("""SELECT teachers.id, teachers.username FROM sessions
                JOIN teachers ON teachers.id=sessions.owner WHERE token_hash=? AND expires>?""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def assignments(self, owner):
        with self.connection() as db:
            return [{"id": r["id"], **json.loads(r["data"]), "created": r["created"]}
                    for r in db.execute("SELECT * FROM assignments WHERE owner=? ORDER BY created DESC", (owner,))]

    def assignment(self, owner, assignment_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM assignments WHERE id=? AND owner=?", (assignment_id, owner)).fetchone()
            if not row:
                raise MissingRecord()
            return {"id": row["id"], **json.loads(row["data"]), "created": row["created"]}

    def create_assignment(self, owner, data):
        record_id = secrets.token_hex(16)
        with self.connection() as db:
            db.execute("INSERT INTO assignments VALUES (?,?,?,?)", (record_id, owner, json.dumps(data), time.time()))
        return self.assignment(owner, record_id)

    def delete_assignment(self, owner, assignment_id):
        self.assignment(owner, assignment_id)
        with self.connection() as db:
            db.execute("DELETE FROM assignments WHERE id=? AND owner=?", (assignment_id, owner))

    def create_submission(self, owner, assignment_id, student_code, pages=()):
        assignment = self.assignment(owner, assignment_id)
        record_id, now = secrets.token_hex(16), time.time()
        data = {"answers": [{"question_id": q["id"], "steps": [], "source_page": None,
                             "unreadable": False, "note": ""} for q in assignment["questions"]],
                "results": [], "page_count": len(pages), "extraction": "manual",
                "message": "Enter or extract the work, then confirm the transcription."}
        with self.connection() as db:
            count = db.execute("SELECT count(*) FROM submissions WHERE assignment_id=?", (assignment_id,)).fetchone()[0]
            if count >= 200:
                raise ValueError("This pilot supports at most 200 submissions per assignment.")
            db.execute("INSERT INTO submissions VALUES (?,?,?,?,?,?,?,?)",
                       (record_id, assignment_id, student_code, "transcription_draft", 1, json.dumps(data), now, now))
            for number, png in enumerate(pages, 1):
                db.execute("INSERT INTO pages VALUES (?,?,?)", (record_id, number, png))
        return self.submission(owner, record_id)

    @staticmethod
    def decode_submission(row):
        return {k: row[k] for k in ("id", "assignment_id", "student_code", "status", "revision", "created", "updated")} | json.loads(row["data"])

    def submission(self, owner, record_id):
        with self.connection() as db:
            row = db.execute("""SELECT s.* FROM submissions s JOIN assignments a ON s.assignment_id=a.id
                WHERE s.id=? AND a.owner=?""", (record_id, owner)).fetchone()
            if not row:
                raise MissingRecord()
            return self.decode_submission(row)

    def submissions(self, owner, assignment_id):
        self.assignment(owner, assignment_id)
        with self.connection() as db:
            return [self.decode_submission(row) for row in db.execute(
                "SELECT * FROM submissions WHERE assignment_id=? ORDER BY created", (assignment_id,))]

    def update_submission(self, owner, record_id, revision, status, data, action):
        self.submission(owner, record_id)
        with self.connection() as db:
            cursor = db.execute("""UPDATE submissions SET status=?,data=?,revision=revision+1,updated=?
                WHERE id=? AND revision=?""", (status, json.dumps(data), time.time(), record_id, revision))
            if cursor.rowcount != 1:
                raise RevisionConflict()
            db.execute("INSERT INTO review_events VALUES (?,?,?,?,?)",
                       (record_id, revision + 1, action, json.dumps(data), time.time()))
        return self.submission(owner, record_id)

    def page(self, owner, record_id, number):
        self.submission(owner, record_id)
        with self.connection() as db:
            row = db.execute("SELECT png FROM pages WHERE submission_id=? AND number=?", (record_id, number)).fetchone()
            if not row:
                raise MissingRecord()
            return row[0]

    def events(self, owner, record_id):
        self.submission(owner, record_id)
        with self.connection() as db:
            return [{"revision": r["revision"], "action": r["action"], "created": r["created"],
                     "data": json.loads(r["data"])} for r in db.execute(
                         "SELECT * FROM review_events WHERE submission_id=? ORDER BY revision", (record_id,))]

    def delete_submission(self, owner, record_id):
        self.submission(owner, record_id)
        with self.connection() as db:
            db.execute("DELETE FROM submissions WHERE id=?", (record_id,))

    def create_practice(self, owner, assignment_id, data):
        self.assignment(owner, assignment_id)
        record_id = secrets.token_hex(16)
        with self.connection() as db:
            db.execute("INSERT INTO practice_sets VALUES (?,?,?,?,?)",
                       (record_id, assignment_id, json.dumps(data), 0, time.time()))
        return self.practice(owner, record_id)

    def practice(self, owner, record_id, approve=False):
        with self.connection() as db:
            row = db.execute("""SELECT p.* FROM practice_sets p JOIN assignments a ON p.assignment_id=a.id
                WHERE p.id=? AND a.owner=?""", (record_id, owner)).fetchone()
            if not row:
                raise MissingRecord()
            if approve:
                db.execute("UPDATE practice_sets SET approved=1 WHERE id=?", (record_id,))
            return {"id": row["id"], "assignment_id": row["assignment_id"],
                    "approved": bool(row["approved"] or approve), **json.loads(row["data"])}

    def practices(self, owner, assignment_id):
        self.assignment(owner, assignment_id)
        with self.connection() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM practice_sets WHERE assignment_id=? ORDER BY created", (assignment_id,))]
        return [self.practice(owner, i) for i in ids]
