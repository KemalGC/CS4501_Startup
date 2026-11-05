"""Restart-safe real inference for the hosted presentation demo."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time

from .oneclick_demo import DemoState, MAX_METRICS_BYTES, _safe_result, summarize_crew_metrics


class HostedDemoState(DemoState):
    """Keep the last verified report, and run each new request in a fresh directory."""

    def __init__(self, video, out_dir, *, command_factory=None):
        self.output_root = Path(out_dir).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.manifest = self.output_root / "latest.json"
        self.source_sha256 = hashlib.sha256(Path(video).read_bytes()).hexdigest()
        self.run_id = secrets.token_hex(16)
        self.feedback_enabled = os.environ.get("STROKESENSE_LLM_FEEDBACK") == "1"
        self.feedback = {"state": "pending" if self.feedback_enabled else "disabled"}
        self.pipeline_pending = False
        super().__init__(video, self.output_root / self.run_id, command_factory=command_factory)
        self._restore()
        if self.feedback_enabled and self.report is not None:
            from .llm_feedback import feedback_status, restore_measured_report
            self.feedback = feedback_status(self.report)
            if self.feedback.get("state") != "generated":
                restore_measured_report(self.report)
                self.feedback = {"state": "running"}
                self.worker = threading.Thread(target=self._upgrade_saved_feedback, daemon=True)
                self.worker.start()

    def _command(self):
        # A live rerun always executes inference, even if another run has a cache.
        return super()._command() + ["--fresh"]

    def _restore(self):
        try:
            if (not self.manifest.is_file() or self.manifest.is_symlink()
                    or self.manifest.stat().st_size > 4096):
                return
            saved = json.loads(self.manifest.read_text())
            if saved.get("source_sha256") != self.source_sha256:
                return
            report = self.output_root / saved["report"]
            metrics = report.parent / "metrics.json"
            if (not _safe_result(self.output_root, report) or report.stat().st_size > 16 * 1024 * 1024
                    or not _safe_result(self.output_root, metrics) or metrics.stat().st_size > MAX_METRICS_BYTES):
                return
            summary = summarize_crew_metrics(json.loads(metrics.read_text()))
            overlay = self.output_root / saved["overlay"] if saved.get("overlay") else None
            if overlay and not _safe_result(self.output_root, overlay):
                overlay = None
            self.report, self.overlay, self.crew_summary = report, overlay, summary
            self.root = self.output_root / report.resolve().relative_to(self.output_root).parts[0]
            self.phase = "finished"
            self.last_end = saved.get("completed_at")
            self.run_id = saved.get("run_id", self.run_id)
        except (OSError, ValueError, TypeError, KeyError):
            # Unverified or incomplete output never becomes a successful report.
            return

    def begin(self):
        with self.lock:
            if self.phase == "running" or (self.worker is not None and self.worker.is_alive()):
                return False
            self.run_id = secrets.token_hex(16)
            self.root = self.output_root / self.run_id
            self.root.mkdir(mode=0o700)
            self.phase = "running"
            self.pipeline_pending = True
            self.feedback = {"state": "pending" if self.feedback_enabled else "disabled"}
            self.error = ""
            self.last_start = time.monotonic()
            self.report = self.overlay = self.crew_summary = None
            self.log = self.root / ".oneclick-analysis.log"
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()
            return True

    def _run(self):
        super()._run()
        try:
            if self.phase == "finished" and self.feedback_enabled:
                self._enrich_feedback(self.report)
            if self.phase == "finished":
                self._persist()
        finally:
            with self.lock:
                self.pipeline_pending = False

    def _upgrade_saved_feedback(self):
        # This upgrades the written feedback only. Saved measured results stay
        # readable, and their pose inference is not repeated on a deployment.
        self._enrich_feedback(self.report)
        self._persist()

    def _enrich_feedback(self, report):
        with self.lock:
            self.feedback = {"state": "running"}
        log = report.parent / ".llm-feedback.log"
        try:
            with log.open("wb") as stream:
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-m", "strokesense.llm_feedback", str(report)],
                    cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                )
                try:
                    code = proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)
                    raise RuntimeError("feedback_timeout")
            if code != 0:
                raise RuntimeError("feedback_generation_failed")
            from .llm_feedback import feedback_status
            result = feedback_status(report)
            if result.get("state") != "generated":
                raise RuntimeError("feedback_validation_failed")
            with self.lock:
                self.feedback = result
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            # HTML and its provenance are separate atomic writes. If the child
            # died between them, never serve unverified prose as current output.
            from .llm_feedback import restore_measured_report
            restore_measured_report(report)
            with self.lock:
                self.feedback = {"state": "failed", "detail": "LLM feedback could not be generated. The measured report remains available."}

    def _persist(self):
        with self.lock:
            self.last_end = time.time()
            if self.phase != "finished":
                return
            saved = {
                "source_sha256": self.source_sha256, "run_id": self.run_id,
                "completed_at": self.last_end,
                "report": str(self.report.relative_to(self.output_root)),
                "overlay": str(self.overlay.relative_to(self.output_root)) if self.overlay else None,
                "llm_feedback": {key: self.feedback[key] for key in
                    ("state", "model", "generated_at", "input_sha256", "report_sha256") if key in self.feedback},
            }
        pending = self.output_root / ".latest.tmp"
        try:
            pending.write_text(json.dumps(saved))
            os.replace(pending, self.manifest)
            # Bound storage while retaining the latest two complete/attempted runs.
            runs = sorted((p for p in self.output_root.iterdir() if p.is_dir() and not p.is_symlink()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            for old in runs[2:]:
                if old != self.root:
                    shutil.rmtree(old)
        except OSError:
            pending.unlink(missing_ok=True)

    def snapshot(self):
        result = super().snapshot()
        with self.lock:
            feedback = dict(self.feedback)
            pending = self.pipeline_pending
        result["llm_feedback"] = feedback
        if pending and result["state"] == "finished":
            writing = feedback.get("state") == "running"
            result.update(state="running", label="Writing coaching feedback" if writing else "Saving report",
                          progress=97, detail="The language model is writing coaching feedback from the measured rowing data." if writing else "Saving the completed analysis report.",
                          has_report=False, has_overlay=False)
        elif result["state"] == "finished" and feedback.get("state") == "running":
            result.update(label="Adding LLM coaching feedback", detail="Your measured report is available. The language model is preparing its feedback.")
        elif result["state"] == "finished" and feedback.get("state") == "generated":
            result["detail"] = "The report includes LLM-generated coaching feedback grounded in the measured rowing data."
        elif result["state"] == "finished" and feedback.get("state") == "failed":
            result["detail"] = feedback["detail"]
        result["run_id"] = self.run_id
        result["can_rerun"] = result["state"] != "running" and not (self.worker is not None and self.worker.is_alive())
        if result["state"] == "failed":
            result["detail"] = result["detail"].replace("private terminal", "Render service logs").replace("local environment", "analysis service")
        return result
