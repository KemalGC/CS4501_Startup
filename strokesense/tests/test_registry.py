"""Offline test-first contract for the local, non-uploading video registry.

All media are synthetic byte fixtures, not actual rowing footage.
The registry does not import the video analysis stack or an LLM.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VideoRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / "private-athlete" / "crew.mp4"
        self.video.parent.mkdir()
        self.video.write_bytes(b"synthetic placeholder for video A")
        self.db = self.root / "private-db" / "clips.sqlite3"

    def registry(self):
        from strokesense import registry
        return registry

    def test_registers_stable_content_id_and_metadata(self):
        registry = self.registry()
        record, created = registry.register_clip(
            self.video, self.db, group_id="practice-1", split="development",
            camera="side-on", fps=29.97,
        )
        self.assertTrue(created)
        self.assertEqual(record["clip_id"], hashlib.sha256(self.video.read_bytes()).hexdigest())
        self.assertEqual(record["sha256"], record["clip_id"])
        self.assertEqual(record["size_bytes"], self.video.stat().st_size)
        self.assertEqual(record["permission"], "unverified")
        self.assertEqual(record["group_id"], "practice-1")
        self.assertEqual(record["split"], "development")
        self.assertEqual(record["camera"], "side-on")
        self.assertEqual(record["fps"], 29.97)
        self.assertEqual(record["review_status"], "unreviewed")
        self.assertNotIn("source_path", record)
        self.assertTrue(self.db.is_file())
        self.assertEqual(len(registry.list_clips(self.db)), 1)

    def test_same_stem_different_content_both_registered(self):
        registry = self.registry()
        other = self.root / "different-session" / "crew.mp4"
        other.parent.mkdir()
        other.write_bytes(b"synthetic placeholder for video B")
        a, a_created = registry.register_clip(self.video, self.db)
        b, b_created = registry.register_clip(other, self.db)
        self.assertTrue(a_created and b_created)
        self.assertNotEqual(a["clip_id"], b["clip_id"])
        self.assertEqual(len(registry.list_clips(self.db)), 2)

    def test_identical_content_duplicate_retains_original_metadata(self):
        registry = self.registry()
        first, created = registry.register_clip(
            self.video, self.db, permission="granted", provenance="signed consent on file",
            group_id="morning", split="development",
        )
        self.assertTrue(created)
        renamed = self.root / "another" / "different-name.mov"
        renamed.parent.mkdir()
        renamed.write_bytes(self.video.read_bytes())
        again, created = registry.register_clip(renamed, self.db)
        self.assertFalse(created)
        self.assertEqual(again["clip_id"], first["clip_id"])
        self.assertEqual(again["permission"], "granted")
        self.assertEqual(again["group_id"], "morning")
        self.assertEqual(len(registry.list_clips(self.db)), 1)
        private = registry.list_clips(self.db, show_paths=True)[0]
        self.assertEqual(private["source_path"], str(self.video.resolve()))

    def test_conflicting_explicit_duplicate_consent_rejected(self):
        registry = self.registry()
        registry.register_clip(self.video, self.db, permission="denied")
        with self.assertRaises(registry.RegistryError):
            registry.register_clip(self.video, self.db, permission="granted",
                                   provenance="unconfirmed assertion")
        self.assertEqual(registry.list_clips(self.db)[0]["permission"], "denied")

    def test_permission_granted_requires_provenance(self):
        registry = self.registry()
        with self.assertRaises(registry.RegistryError):
            registry.register_clip(self.video, self.db, permission="granted")
        self.assertEqual(registry.list_clips(self.db), [])
        record, _ = registry.register_clip(self.video, self.db, permission="denied")
        self.assertEqual(record["permission"], "denied")

    def test_grouped_split_conflict_does_not_write_row(self):
        registry = self.registry()
        registry.register_clip(self.video, self.db, group_id="same-crew-session",
                               split="development")
        other = self.root / "other.mp4"
        other.write_bytes(b"synthetic independent recording")
        with self.assertRaises(registry.RegistryError):
            registry.register_clip(other, self.db, group_id="same-crew-session",
                                   split="heldout")
        self.assertEqual(len(registry.list_clips(self.db)), 1)
        with self.assertRaises(registry.RegistryError):
            registry.register_clip(other, self.db, split="heldout")
        self.assertEqual(len(registry.list_clips(self.db)), 1)

    def test_listing_hides_private_path_and_provenance(self):
        registry = self.registry()
        registry.register_clip(self.video, self.db, permission="granted",
                               provenance="private-form-ID-99")
        rows = registry.list_clips(self.db)
        serialized = json.dumps(rows)
        self.assertNotIn(str(self.video.parent), serialized)
        self.assertNotIn("private-form-ID-99", serialized)
        self.assertNotIn("source_path", serialized)
        private = registry.list_clips(self.db, show_paths=True)
        self.assertEqual(private[0]["source_path"], str(self.video.resolve()))

    def test_cli_import_list_and_no_full_path_in_output(self):
        registry = self.registry()
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            code = registry.main(["import", str(self.video), "--db", str(self.db)])
        self.assertEqual(code, 0)
        result = json.loads(capture.getvalue())
        self.assertTrue(result["created"])
        self.assertNotIn(str(self.video.parent), capture.getvalue())
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            self.assertEqual(registry.main(["list", "--db", str(self.db)]), 0)
        self.assertEqual(len(json.loads(capture.getvalue())), 1)

    def test_missing_empty_or_invalid_fps_rejected(self):
        registry = self.registry()
        with self.assertRaises((FileNotFoundError, registry.RegistryError)):
            registry.register_clip(self.root / "missing.mp4", self.db)
        for bad in (0, -1, float("nan"), float("inf")):
            with self.subTest(fps=bad), self.assertRaises(registry.RegistryError):
                registry.register_clip(self.video, self.db, fps=bad)
        self.assertEqual(registry.list_clips(self.db), [])
        empty = self.root / "empty.mp4"
        empty.write_bytes(b"")
        with self.assertRaises(registry.RegistryError):
            registry.register_clip(empty, self.db)
        self.assertEqual(registry.list_clips(self.db), [])

    def test_mid_hash_mutation_rejected_before_insert(self):
        registry = self.registry()
        original = registry._stream_sha256
        def mutate(path):
            digest = original(path)
            self.video.write_bytes(b"changed synthetic video while hashing")
            return digest
        with patch.object(registry, "_stream_sha256", side_effect=mutate):
            with self.assertRaises(registry.RegistryError):
                registry.register_clip(self.video, self.db)
        self.assertEqual(registry.list_clips(self.db), [])


if __name__ == "__main__":
    unittest.main()
