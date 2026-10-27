"""Privacy-safe SQLite schema/audit tests with synthetic placeholder clips.

These are NOT real athlete permission records or recordings.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import registry


class RegistryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "private" / "registry.sqlite3"
        self.clip = self.root / "private-athlete.mov"
        self.clip.write_bytes(b"test fixture: not actual footage")
        self.provenance = "private-operator-assertion"

    def grant(self):
        return registry.register_clip(
            self.clip, self.db, permission="granted",
            provenance=self.provenance, group_id="practice-A",
            split="development",
        )[0]

    def test_new_registry_has_versioned_schema_and_null_audit_date(self):
        row = self.grant()
        self.assertIsNone(row["revoked_utc"])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            fields = {col[1] for col in conn.execute("PRAGMA table_info(clips)")}
            self.assertIn("revoked_utc", fields)

    def test_first_withdrawal_sets_utc_once_without_losing_private_fields(self):
        row = self.grant()
        start = datetime.now(timezone.utc)
        first = registry.revoke_clip(row["clip_id"], self.db)
        end = datetime.now(timezone.utc)
        again = registry.revoke_clip(row["clip_id"], self.db)
        self.assertEqual(first, again)
        self.assertEqual(first["permission"], "denied")
        when = datetime.fromisoformat(first["revoked_utc"])
        self.assertIsNotNone(when.tzinfo)
        self.assertLessEqual(start, when)
        self.assertLessEqual(when, end)
        self.assertNotIn(str(self.root), json.dumps(first))
        self.assertNotIn(self.provenance, json.dumps(first))
        with sqlite3.connect(self.db) as conn:
            saved = conn.execute(
                "SELECT source_path, provenance, split, revoked_utc "
                "FROM clips WHERE clip_id=?", (row["clip_id"],)
            ).fetchone()
        self.assertEqual(saved[0], str(self.clip.resolve()))
        self.assertEqual(saved[1], self.provenance)
        self.assertEqual(saved[2], "development")
        self.assertEqual(saved[3], first["revoked_utc"])
        self.assertTrue(self.clip.exists())  # No data deletion.

    def test_denied_at_import_has_unknown_withdrawal_time(self):
        item, _ = registry.register_clip(self.clip, self.db, permission="denied")
        self.assertIsNone(item["revoked_utc"])
        later = registry.revoke_clip(item["clip_id"], self.db)
        self.assertIsNone(later["revoked_utc"])
        self.assertEqual(later["permission"], "denied")

    def test_legacy_unversioned_registry_migrates_without_rewriting_rows(self):
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as conn:
            conn.executescript(registry._SCHEMA)
            conn.execute(
                "INSERT INTO clips (clip_id, sha256, size_bytes, source_path, "
                "source_mtime_ns, permission, provenance, group_id, split, "
                "camera, fps, annotation_version, review_status, created_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("a" * 64, "a" * 64, len(self.clip.read_bytes()),
                 str(self.clip.resolve()), self.clip.stat().st_mtime_ns,
                 "denied", self.provenance, "session-Z", "heldout",
                 "side", 29.97, None, "unreviewed",
                 "2026-01-01T00:00:00+00:00"),
            )
            conn.execute("PRAGMA user_version = 0")
        rows = registry.list_clips(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clip_id"], "a" * 64)
        self.assertEqual(rows[0]["split"], "heldout")
        self.assertIsNone(rows[0]["revoked_utc"])  # No false history.
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute(
                "SELECT provenance FROM clips"
            ).fetchone()[0], self.provenance)

    def test_future_schema_version_fails_closed_without_mutation(self):
        self.grant()
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(registry.RegistryError):
            registry.list_clips(self.db)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 99)
            self.assertEqual(conn.execute("SELECT count(*) FROM clips").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
