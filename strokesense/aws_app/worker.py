"""Run a real StrokeSense CPU analysis in one isolated AWS Batch task.

Batch supplies server-authored S3 keys. This worker downloads a bounded upload,
runs the existing Render CPU analysis command and only publishes report.json
after checking the generated HTML and measurements. Failure always exits
nonzero so the API's Batch-status reconciler refunds reserved free quota.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping


LOGGER = logging.getLogger(__name__)
FREE_MAX_VIDEO_BYTES = 100_000_000
MAX_METRICS_BYTES = 16 * 1024 * 1024
MAX_HTML_BYTES = 24 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 3300
_JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
_USER_HASH = re.compile(r"[a-f0-9]{24}\Z")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_EXTENSIONS = frozenset((".mp4", ".mov", ".webm"))


class WorkerError(RuntimeError):
    """A fixed safe failure category, never an AWS error or media path."""


def _require_config(env: Mapping[str, str]) -> tuple[str, str, str, str]:
    job = env.get("STROKESENSE_JOB_ID", "")
    user_hash = env.get("STROKESENSE_USER_HASH", "")
    bucket = env.get("STROKESENSE_S3_BUCKET", "")
    input_key = env.get("STROKESENSE_INPUT_KEY", "")
    report_key = env.get("STROKESENSE_REPORT_KEY", "")
    if not _JOB_ID.fullmatch(job) or not _USER_HASH.fullmatch(user_hash):
        raise WorkerError("invalid_job_identity")
    if not _BUCKET.fullmatch(bucket):
        raise WorkerError("invalid_storage_configuration")
    if not any(input_key == f"uploads/{user_hash}/{job}/original{ext}" for ext in _EXTENSIONS):
        raise WorkerError("invalid_input_key")
    if report_key != f"reports/free/{user_hash}/{job}/report.json":
        # Paid jobs remain disabled until GPU billing is implemented.
        raise WorkerError("paid_analysis_disabled_or_invalid_report_key")
    return bucket, input_key, report_key, Path(input_key).suffix


def _download_bounded(s3: Any, bucket: str, key: str, destination: Path) -> None:
    metadata = s3.head_object(Bucket=bucket, Key=key)
    length = metadata.get("ContentLength")
    if type(length) is not int or not 0 < length <= FREE_MAX_VIDEO_BYTES:
        raise WorkerError("invalid_media_size")
    stream = s3.get_object(Bucket=bucket, Key=key).get("Body")
    if stream is None or not callable(getattr(stream, "read", None)):
        raise WorkerError("invalid_media_stream")
    received = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = stream.read(min(1024 * 1024, FREE_MAX_VIDEO_BYTES + 1 - received))
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise WorkerError("invalid_media_stream")
                received += len(chunk)
                if received > FREE_MAX_VIDEO_BYTES:
                    raise WorkerError("invalid_media_size")
                output.write(chunk)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    if received != length:
        raise WorkerError("incomplete_video_download")


def _run_real_pipeline(video: Path, results: Path, timeout: int) -> None:
    """Execute the existing Render production CPU command, never a shell."""
    command = [
        sys.executable, "-u", "-m", "strokesense.cli", str(video),
        "--out", str(results), "--fps", "10", "--dominant-crew",
        "--threads", "2", "--fresh", "--bounded-media",
    ]
    try:
        completed = subprocess.run(
            command, timeout=timeout, check=False,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("analysis_timeout") from exc
    except OSError as exc:
        raise WorkerError("analysis_process_unavailable") from exc
    if completed.returncode != 0:
        raise WorkerError("analysis_failed")


def _bounded_file(path: Path, root: Path, max_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise WorkerError("invalid_analysis_artifact")
    with path.open("rb") as handle:
        contents = handle.read(max_bytes + 1)
    if not contents or len(contents) > max_bytes:
        raise WorkerError("invalid_analysis_artifact_size")
    return contents


def _report_payload(results: Path, job_id: str) -> bytes:
    # Every task has a fresh temporary root. A missing/duplicated result cannot
    # become a successful Batch job, even if a subprocess exits with zero.
    reports = list(results.rglob("report.html"))
    if len(reports) != 1:
        raise WorkerError("missing_or_ambiguous_report")
    html_file = reports[0]
    html_bytes = _bounded_file(html_file, results, MAX_HTML_BYTES)
    metrics_bytes = _bounded_file(html_file.with_name("metrics.json"), results, MAX_METRICS_BYTES)
    try:
        html = html_bytes.decode("utf-8")
        metrics = json.loads(metrics_bytes)
    except (UnicodeError, ValueError) as exc:
        raise WorkerError("invalid_analysis_artifact") from exc
    if "<html" not in html.lower() or "</html>" not in html.lower():
        raise WorkerError("invalid_analysis_report")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("rowers"), list):
        raise WorkerError("invalid_analysis_metrics")
    if not any(
        isinstance(rower, dict) and isinstance(rower.get("strokes"), list)
        and len(rower["strokes"]) > 0 for rower in metrics["rowers"]
    ):
        raise WorkerError("no_usable_strokes")
    data = {
        "schema_version": "strokesense-free-report-v1",
        "job_id": job_id,
        "tier": "free",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_method": "CPU ONNX pose tracking and measured rowing technique",
        "coach_validated": False,
        "report_html": html,  # already self-contained with charts and photos
        "metrics": metrics,
    }
    try:
        payload = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WorkerError("invalid_analysis_metrics") from exc
    if len(payload) > MAX_REPORT_BYTES:
        raise WorkerError("report_too_large")
    return payload


def run_job(
    *, env: Mapping[str, str] | None = None, s3: Any = None,
    pipeline: Callable[[Path, Path, int], None] = _run_real_pipeline,
) -> None:
    """Process exactly one job; local tests may inject simulated S3/inference."""
    config = os.environ if env is None else env
    bucket, input_key, report_key, extension = _require_config(config)
    if s3 is None:
        import boto3  # Deployed Fargate only; unit tests do not need the SDK.
        s3 = boto3.client("s3")
    raw_timeout = config.get("STROKESENSE_ANALYSIS_TIMEOUT_SECONDS", str(DEFAULT_ANALYSIS_TIMEOUT_SECONDS))
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise WorkerError("invalid_analysis_timeout") from exc
    if not 30 <= timeout <= 3300:
        raise WorkerError("invalid_analysis_timeout")

    with tempfile.TemporaryDirectory(prefix="strokesense-fargate-") as temporary:
        root = Path(temporary)
        video = root / f"original{extension}"
        results = root / "results"
        results.mkdir(mode=0o700)
        _download_bounded(s3, bucket, input_key, video)
        pipeline(video, results, timeout)
        payload = _report_payload(results, config["STROKESENSE_JOB_ID"])
        # This is the final success commit. The API checks that this object
        # exists before ever settling a Batch job as successful.
        s3.put_object(
            Bucket=bucket, Key=report_key, Body=payload,
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256",
            CacheControl="private, no-store",
        )
        LOGGER.info("StrokeSense CPU job completed with verified report (%d bytes).", len(payload))


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        run_job()
    except WorkerError as exc:
        LOGGER.error("StrokeSense CPU job failed (%s); no completed result.", exc)
        return 2
    except Exception:
        # AWS/native decoder exception messages can contain private S3 keys or
        # file paths. Log a fixed category instead of exposing exception text.
        LOGGER.error("StrokeSense CPU job failed (internal_error); no completed result.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
