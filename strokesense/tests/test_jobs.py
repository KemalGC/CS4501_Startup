"""Deterministic local analysis job lifecycle tests (no model/video inference)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.registry import register_clip


class LocalJobsTests(unittest.TestCase):
    def setUp(self):
        from strokesense.jobs import JobQueue
        self.JobQueue = JobQueue
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clip = self.root / "private-session.mov"
        self.clip.write_bytes(b"synthetic video fixture - not decodable media")
        self.registry_db = self.root / "registry.sqlite3"
        self.jobs_db = self.root / "jobs.sqlite3"
        self.out_dir = self.root / "results"
        self.clip_id = register_clip(
            self.clip, self.registry_db, permission="granted",
            provenance="synthetic test operator claim", group_id="fixture-session",
        )[0]["clip_id"]
        self.calls = Mock(side_effect=self.fake_runner)

    def fake_runner(self, video, *, out_dir):
        self.assertEqual(Path(video), self.clip)
        out = Path(out_dir) / "report-output"
        out.mkdir(parents=True, exist_ok=True)
        report = out / "report.html"
        report.write_text("<h1>synthetic report</h1>", encoding="utf-8")
        return {"report": report}

    def queue(self, **kwargs):
        return self.JobQueue(
            registry_db=self.registry_db, job_db=self.jobs_db,
            results_root=self.out_dir, analyze_fn=self.calls, **kwargs,
        )

    def test_job_completes_with_private_scoped_result_and_durable_status(self):
        with self.queue() as manager:
            queued = manager.submit(self.clip_id)
            self.assertEqual(queued["status"], "queued")
            job_id = queued["job_id"]
            self.assertNotIn(str(self.clip), json.dumps(queued))
            finished = manager.wait(job_id, timeout=5)
            self.assertEqual(finished["status"], "succeeded")
            self.assertTrue(finished["report_path"].endswith("/report.html"))
            self.assertFalse(Path(finished["report_path"]).is_absolute())
            self.assertIn(job_id, finished["report_path"])
            self.assertNotIn(str(self.root), json.dumps(finished))
            self.assertEqual(self.calls.call_count, 1)
        with self.queue() as again:
            self.assertEqual(again.get(job_id)["status"], "succeeded")

    def test_successful_report_digest_is_private_and_durable(self):
        with self.queue() as manager:
            job_id = manager.submit(self.clip_id)["job_id"]
            done = manager.wait(job_id, timeout=5)
            self.assertEqual(done["status"], "succeeded")
            report = self.out_dir / done["report_path"]
            expected = hashlib.sha256(report.read_bytes()).hexdigest()
            self.assertEqual(manager.report_sha256(job_id), expected)
            self.assertNotIn("report_sha256", json.dumps(done))
        with self.queue() as manager:
            self.assertEqual(manager.report_sha256(job_id), expected)
            self.assertNotIn("report_sha256", json.dumps(manager.list_recent()))

    def test_version_two_jobs_migrate_without_deleting_history(self):
        legacy_id = "a" * 32
        with sqlite3.connect(self.jobs_db) as conn:
            conn.execute(
                "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, "
                "status TEXT NOT NULL, created_utc TEXT NOT NULL, "
                "started_utc TEXT, finished_utc TEXT, report_path TEXT, "
                "error_code TEXT, coaching_state TEXT NOT NULL DEFAULT 'withheld')"
            )
            conn.execute(
                "INSERT INTO jobs "
                "(job_id,clip_id,status,created_utc,report_path,coaching_state) "
                "VALUES (?,?,?,?,?,?)",
                (legacy_id, self.clip_id, "succeeded",
                 "2026-01-01T00:00:00Z", legacy_id + "/report.html", "withheld"),
            )
            conn.execute("PRAGMA user_version = 2")

        with self.queue() as manager:
            old = manager.get(legacy_id)
            self.assertIsNotNone(old)
            self.assertEqual(old["status"], "succeeded")
            self.assertEqual(old["coaching_state"], "withheld")
            self.assertIsNone(manager.report_sha256(legacy_id))
        with sqlite3.connect(self.jobs_db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertIn("report_sha256", [
                c[1] for c in conn.execute("PRAGMA table_info(jobs)")
            ])

    def test_version_three_jobs_preserve_history_with_unbound_metrics(self):
        legacy_id = "b" * 32
        with sqlite3.connect(self.jobs_db) as conn:
            conn.execute(
                "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, "
                "status TEXT NOT NULL, created_utc TEXT NOT NULL, "
                "started_utc TEXT, finished_utc TEXT, report_path TEXT, "
                "report_sha256 TEXT, error_code TEXT, "
                "coaching_state TEXT NOT NULL DEFAULT 'withheld')"
            )
            conn.execute(
                "INSERT INTO jobs (job_id,clip_id,status,created_utc,"
                "report_path,report_sha256,coaching_state) "
                "VALUES (?,?,?,?,?,?,?)",
                (legacy_id, self.clip_id, "succeeded", "2026-01-01T00:00:00Z",
                 legacy_id + "/report.html", "a" * 64, "withheld"),
            )
            conn.execute("PRAGMA user_version = 3")
        with self.queue() as manager:
            self.assertEqual(manager.get(legacy_id)["status"], "succeeded")
            self.assertEqual(manager.report_sha256(legacy_id), "a" * 64)
            self.assertIsNone(manager.metrics_sha256(legacy_id))
        with sqlite3.connect(self.jobs_db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertIn("metrics_sha256", [
                row[1] for row in conn.execute("PRAGMA table_info(jobs)")
            ])

    def test_version_four_jobs_preserve_reports_when_media_fields_added(self):
        """Upgrade to media-aware schema without pretending old media is bound."""
        legacy_id = "c" * 32
        with sqlite3.connect(self.jobs_db) as conn:
            conn.execute(
                "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, "
                "status TEXT NOT NULL, created_utc TEXT NOT NULL, "
                "started_utc TEXT, finished_utc TEXT, report_path TEXT, "
                "report_sha256 TEXT, metrics_sha256 TEXT, error_code TEXT, "
                "coaching_state TEXT NOT NULL DEFAULT 'withheld')"
            )
            conn.execute(
                "INSERT INTO jobs (job_id,clip_id,status,created_utc,"
                "report_path,report_sha256,metrics_sha256,coaching_state) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (legacy_id, self.clip_id, "succeeded", "2026-01-01T00:00:00Z",
                 legacy_id + "/report.html", "a" * 64, "b" * 64, "withheld"),
            )
            conn.execute("PRAGMA user_version = 4")
        with self.queue() as manager:
            self.assertEqual(manager.get(legacy_id)["status"], "succeeded")
            self.assertEqual(manager.report_sha256(legacy_id), "a" * 64)
            self.assertEqual(manager.metrics_sha256(legacy_id), "b" * 64)
            self.assertIsNone(manager.media_artifact(legacy_id))
        with sqlite3.connect(self.jobs_db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            self.assertTrue({"video_path", "video_sha256"}.issubset(columns))

    def test_oversized_generated_artifacts_fail_before_success(self):
        """A successful analyzer must not publish unreadable oversized output."""
        for artifact in ("report", "metrics"):
            with self.subTest(artifact=artifact):
                def analyzer(_video, *, out_dir):
                    folder = Path(out_dir) / "analyzed"
                    folder.mkdir()
                    report = folder / "report.html"
                    report.write_bytes(
                        b"oversized synthetic report" if artifact == "report"
                        else b"ok"
                    )
                    if artifact == "metrics":
                        (folder / "metrics.json").write_bytes(
                            b"oversized synthetic metrics"
                        )
                    return {"report": report}

                self.calls.side_effect = analyzer
                with (patch("strokesense.jobs.MAX_REPORT_BYTES", 8, create=True),
                      patch("strokesense.jobs.MAX_METRICS_BYTES", 8, create=True)):
                    with self.queue() as manager:
                        job_id = manager.submit(self.clip_id)["job_id"]
                        done = manager.wait(job_id, timeout=5)
                self.assertEqual(done["status"], "failed")
                self.assertEqual(done["error_code"], "result_too_large")
                self.assertIsNone(done["report_path"])
                self.assertEqual(done["coaching_state"], "withheld")
                self.assertNotIn(str(self.root), json.dumps(done))

    def test_missing_or_unverified_clip_is_rejected_without_enqueuing(self):
        from strokesense.jobs import JobError
        with self.queue() as manager:
            with self.assertRaises(JobError):
                manager.submit("not-a-registered-clip")
        unverified = self.root / "unverified.mov"
        unverified.write_bytes(b"other synthetic fixture")
        other = register_clip(unverified, self.registry_db)[0]["clip_id"]
        with self.queue() as manager:
            with self.assertRaises(JobError):
                manager.submit(other)
        self.calls.assert_not_called()

    def test_source_replacement_after_registration_fails_closed(self):
        self.clip.write_bytes(b"modified synthetic video fixture, still no real video")
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "source_changed")
        self.calls.assert_not_called()

    def test_runner_exception_is_sanitized_and_not_retried(self):
        self.calls.side_effect = RuntimeError("secret name /private/path token")
        with self.queue() as manager:
            started = manager.submit(self.clip_id)
            finished = manager.wait(started["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "analysis_failed")
        self.assertNotIn("secret", json.dumps(finished))
        self.assertNotIn(str(self.clip), json.dumps(finished))
        self.assertEqual(self.calls.call_count, 1)

    def test_no_rowing_motion_results_in_specific_failure(self):
        self.calls.side_effect = lambda *args, **kwargs: None
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "no_rowing_detected")

    def test_report_outside_job_root_is_never_published(self):
        outside = self.root / "private" / "report.html"
        outside.parent.mkdir()
        outside.write_text("not permitted")
        self.calls.side_effect = lambda *args, **kwargs: {"report": outside}
        with self.queue() as manager:
            record = manager.submit(self.clip_id)
            finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "invalid_report_location")
        self.assertIsNone(finished["report_path"])

    def test_capacity_limit_rejects_second_job_during_running_first(self):
        from strokesense.jobs import JobError
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return self.fake_runner(*args, **kwargs)
        self.calls.side_effect = slow
        with self.queue(max_pending=1) as manager:
            first = manager.submit(self.clip_id)
            self.assertTrue(entered.wait(timeout=3))
            with self.assertRaises(JobError):
                manager.submit(self.clip_id)
            release.set()
            self.assertEqual(manager.wait(first["job_id"], timeout=5)["status"], "succeeded")


    def test_output_directory_failure_returns_safe_failed_status(self):
        with self.queue() as manager:
            with patch("strokesense.jobs.Path.mkdir",
                       side_effect=OSError("secret absolute filesystem path")):
                record = manager.submit(self.clip_id)
                finished = manager.wait(record["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "output_unavailable")
        self.assertNotIn("secret", json.dumps(finished))
        self.calls.assert_not_called()

    def test_unknown_status_id_does_not_expose_records(self):
        with self.queue() as manager:
            self.assertIsNone(manager.get("unknown-id"))
            self.assertIsNone(manager.get("../../private-session.mov"))
            self.assertIsNone(manager.get(""))
            with self.assertRaises(ValueError):
                manager.wait("unknown-id", timeout=1)


    def test_source_mutates_during_analysis_never_publishes_report(self):
        def mutate_during_run(video, *, out_dir):
            result = self.fake_runner(video, out_dir=out_dir)
            info = self.clip.stat()
            prior = self.clip.read_bytes()
            self.clip.write_bytes(b"x" * len(prior))
            os.utime(self.clip, ns=(info.st_atime_ns, info.st_mtime_ns))
            return result

        self.calls.side_effect = mutate_during_run
        with self.queue() as manager:
            queued = manager.submit(self.clip_id)
            finished = manager.wait(queued["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "source_changed")
        self.assertIsNone(finished["report_path"])
        self.assertNotIn(str(self.clip), json.dumps(finished))

    def test_source_removed_during_analysis_never_publishes_report(self):
        def delete_during_run(video, *, out_dir):
            result = self.fake_runner(video, out_dir=out_dir)
            self.clip.unlink()
            return result

        self.calls.side_effect = delete_during_run
        with self.queue() as manager:
            queued = manager.submit(self.clip_id)
            finished = manager.wait(queued["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "source_changed")
        self.assertIsNone(finished["report_path"])


    def test_production_worker_rejects_invalid_media_without_pose(self):
        # No real model call: old behavior accepts fake runner output, while
        # preflight must fail on intentionally non-decodable source bytes.
        with patch("strokesense.cli.analyse_video", return_value={"report": "fake"}) as analyze:
            with self.JobQueue(
                registry_db=self.registry_db, job_db=self.jobs_db,
                results_root=self.out_dir,
            ) as queue:
                item = queue.submit(self.clip_id)
                finished = queue.wait(item["job_id"], timeout=5)
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_code"], "invalid_media")
        self.assertIsNone(finished["report_path"])
        self.assertNotIn(str(self.clip), json.dumps(finished))
        analyze.assert_not_called()

    def test_decoder_preflight_valid_frame_then_runs_existing_analyzer(self):
        import cv2
        from strokesense.jobs import _default_analyze
        fake_capture = Mock()
        fake_capture.isOpened.return_value = True
        values = {
            cv2.CAP_PROP_FRAME_WIDTH: 640.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 480.0,
            cv2.CAP_PROP_FPS: 25.0,
            cv2.CAP_PROP_FRAME_COUNT: 60.0,
        }
        fake_capture.get.side_effect = values.__getitem__
        fake_capture.read.return_value = (
            True, Mock(shape=(480, 640, 3)),
        )
        sentinel = {"report": "mocked successful analysis"}
        with patch("cv2.VideoCapture", return_value=fake_capture) as opened, \
                patch("strokesense.cli.analyse_video", return_value=sentinel) as analyze:
            self.assertIs(
                _default_analyze(self.clip, out_dir=self.out_dir), sentinel
            )
        opened.assert_called_once_with(str(self.clip))
        fake_capture.release.assert_called_once_with()
        analyze.assert_called_once_with(self.clip, out_dir=self.out_dir)

    def test_decoder_preflight_rejects_bad_metadata_and_missing_frames(self):
        import cv2
        from strokesense.jobs import _default_analyze
        for fps, shape, frame_ok in (
            (float("nan"), (480, 640, 3), True),
            (25.0, (480, 640, 3), False),
            (25.0, (0, 640, 3), True),
        ):
            with self.subTest(fps=fps, shape=shape, frame_ok=frame_ok):
                fake_capture = Mock()
                fake_capture.isOpened.return_value = True
                fake_capture.get.side_effect = lambda key: {
                    cv2.CAP_PROP_FRAME_WIDTH: 640,
                    cv2.CAP_PROP_FRAME_HEIGHT: 480,
                    cv2.CAP_PROP_FPS: fps,
                    cv2.CAP_PROP_FRAME_COUNT: 60.0,
                }[key]
                fake_capture.read.return_value = (frame_ok, Mock(shape=shape))
                with patch("cv2.VideoCapture", return_value=fake_capture), \
                        patch("strokesense.cli.analyse_video") as analyze:
                    with self.assertRaises(ValueError):
                        _default_analyze(self.clip, out_dir=self.out_dir)
                fake_capture.release.assert_called_once_with()
                analyze.assert_not_called()


    def test_decoder_preflight_smoke_on_generated_toy_avi(self):
        """Actually decode synthetic computer-generated frames, never user footage."""
        import cv2
        import numpy as np
        from strokesense.jobs import _default_analyze
        from strokesense.media import probe_decodable_video
        clip = self.root / "synthetic-decodable.avi"
        writer = cv2.VideoWriter(str(clip),
                                 cv2.VideoWriter_fourcc(*"MJPG"), 15.0,
                                 (160, 120))
        if not writer.isOpened():
            self.skipTest("local OpenCV build lacks MJPG AVI video writer")
        try:
            for index in range(3):
                frame = np.zeros((120, 160, 3), dtype=np.uint8)
                frame[20:60, 10 + 20 * index:50 + 20 * index] = 255
                writer.write(frame)
        finally:
            writer.release()
        self.assertTrue(clip.is_file())
        self.assertTrue(probe_decodable_video(clip))
        sentinel = {"report": "stubbed: no inference"}
        with patch("strokesense.cli.analyse_video", return_value=sentinel) as analyze:
            self.assertIs(_default_analyze(clip, out_dir=self.out_dir), sentinel)
        analyze.assert_called_once_with(clip, out_dir=self.out_dir)

    def test_decoder_preflight_refuses_unknown_or_overlong_video_metadata(self):
        import cv2
        from strokesense.jobs import _default_analyze
        cases = (
            ("missing frame count", 0.0),
            ("nonfinite frame count", float("nan")),
            ("negative frame count", -2.0),
            ("over two minutes", 30.0 * 121.0),
        )
        for label, frame_count in cases:
            with self.subTest(case=label):
                fake_capture = Mock()
                fake_capture.isOpened.return_value = True
                fake_capture.get.side_effect = lambda key: {
                    cv2.CAP_PROP_FRAME_WIDTH: 640.0,
                    cv2.CAP_PROP_FRAME_HEIGHT: 480.0,
                    cv2.CAP_PROP_FPS: 30.0,
                    cv2.CAP_PROP_FRAME_COUNT: frame_count,
                }[key]
                fake_capture.read.return_value = (
                    True, Mock(shape=(480, 640, 3)),
                )
                with patch("cv2.VideoCapture", return_value=fake_capture), \
                        patch("strokesense.cli.analyse_video") as analyze:
                    with self.assertRaises(ValueError):
                        _default_analyze(self.clip, out_dir=self.out_dir)
                analyze.assert_not_called()
                fake_capture.read.assert_not_called()
                fake_capture.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
