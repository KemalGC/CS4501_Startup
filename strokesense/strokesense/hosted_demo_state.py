"""Restart-safe real inference for the hosted presentation demo."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
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
        super().__init__(video, self.output_root / self.run_id, command_factory=command_factory)
        self._restore()

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
            self.error = ""
            self.last_start = time.monotonic()
            self.report = self.overlay = self.crew_summary = None
            self.log = self.root / ".oneclick-analysis.log"
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()
            return True

    def _run(self):
        super()._run()
        with self.lock:
            self.last_end = time.time()
            if self.phase != "finished":
                return
            saved = {
                "source_sha256": self.source_sha256, "run_id": self.run_id,
                "completed_at": self.last_end,
                "report": str(self.report.relative_to(self.output_root)),
                "overlay": str(self.overlay.relative_to(self.output_root)) if self.overlay else None,
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
        result["run_id"] = self.run_id
        result["can_rerun"] = result["state"] != "running"
        if result["state"] == "failed":
            result["detail"] = result["detail"].replace("private terminal", "Render service logs").replace("local environment", "analysis service")
        return result
