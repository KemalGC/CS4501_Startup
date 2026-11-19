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
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping

from . import artifacts


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


def _media_manifest(results: Path) -> tuple[dict[str, Any], list[tuple[Path, str, str, int]]]:
    """Collect only bounded media explicitly produced beside this run's report.

    The resulting paths are fixed within a private, owner/job-specific prefix.
    A generated gallery cannot choose S3 destinations or read outside results.
    """
    reports = list(results.rglob("report.html"))
    if len(reports) != 1:
        raise WorkerError("missing_or_ambiguous_report")
    directory = reports[0].parent
    rows: dict[str, Any] = {}
    gallery = directory / "mistake_frames.json"
    if gallery.exists() or gallery.is_symlink():
        try:
            raw = json.loads(_bounded_file(gallery, results, artifacts.MAX_MANIFEST_BYTES))
            if type(raw.get("version")) is not int or raw["version"] != 1:
                raise artifacts.InvalidArtifactManifest("invalid_gallery_version")
            rows = artifacts.validate_rowers(raw.get("rowers"))
        except (ValueError, TypeError, UnicodeError, AttributeError) as exc:
            raise WorkerError("invalid_media_manifest") from exc

    specs: list[tuple[Path, str, str, int]] = []
    video = directory / "original_annotated.mp4"
    if video.exists() or video.is_symlink():
        size = _artifact_size(video, results, artifacts.MAX_VIDEO_BYTES)
        with video.open("rb") as handle:
            if handle.read(12)[4:8] != b"ftyp":
                raise WorkerError("invalid_annotated_video")
        specs.append((video, artifacts.VIDEO_NAME, "video/mp4", size))

    names = artifacts.frame_names(rows)
    if len(names) > artifacts.MAX_PHOTO_COUNT:
        raise WorkerError("too_many_gallery_frames")
    photo_total = 0
    for filename in sorted(names):
        photo = directory / filename
        size = _artifact_size(photo, results, artifacts.MAX_PHOTO_BYTES)
        photo_total += size
        if photo_total > artifacts.MAX_PHOTO_TOTAL_BYTES:
            raise WorkerError("gallery_too_large")
        with photo.open("rb") as handle:
            if handle.read(3) != b"\xff\xd8\xff":
                raise WorkerError("invalid_gallery_photo")
        specs.append((photo, f"frames/{filename}", "image/jpeg", size))

    return {
        "schema_version": artifacts.SCHEMA,
        "video_available": any(name == artifacts.VIDEO_NAME for _, name, _, _ in specs),
        "rowers": rows,
    }, specs


def _artifact_size(path: Path, root: Path, maximum: int) -> int:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise WorkerError("invalid_media_artifact")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise WorkerError("invalid_media_artifact_size")
    return size


def _publish_media(s3: Any, bucket: str, report_key: str, results: Path) -> None:
    manifest, specs = _media_manifest(results)
    if not specs:
        return  # Legacy or minimal analyses have only the self-contained HTML.
    prefix = report_key.removesuffix("report.json")
    for path, relative_key, content_type, size in specs:
        with path.open("rb") as source:
            s3.put_object(
                Bucket=bucket, Key=prefix + relative_key,
                Body=source, ContentLength=size,
                ContentType=content_type, ServerSideEncryption="AES256",
                CacheControl="private, no-store",
            )
    manifest_bytes = json.dumps(manifest, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(manifest_bytes) > artifacts.MAX_MANIFEST_BYTES:
        raise WorkerError("media_manifest_too_large")
    s3.put_object(
        Bucket=bucket, Key=prefix + artifacts.MANIFEST_NAME,
        Body=manifest_bytes, ContentType="application/json; charset=utf-8",
        ServerSideEncryption="AES256", CacheControl="private, no-store",
    )
def _video_duration_ms(video: Path) -> int | None:
    """Best-effort source container duration; never invent duration on failure."""
    capture = None
    try:
        import cv2
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            return None
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or not math.isfinite(frames) or fps <= 0 or frames <= 0:
            return None
        duration = frames / fps
        if not 0 < duration <= 3600:
            return None
        return int(round(duration * 1000))
    except Exception:
        return None
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass


def _child_cpu_seconds() -> float:
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return float(usage.ru_utime + usage.ru_stime)
    except Exception:
        return 0.0


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
        worker_start = time.perf_counter()
        root = Path(temporary)
        video = root / f"original{extension}"
        results = root / "results"
        results.mkdir(mode=0o700)
        _download_bounded(s3, bucket, input_key, video)
        video_duration_ms = _video_duration_ms(video)
        child_cpu_start = _child_cpu_seconds()
        pipeline_start = time.perf_counter()
        pipeline(video, results, timeout)
        analysis_wall_ms = int(round((time.perf_counter() - pipeline_start) * 1000))
        cpu_time_ms = max(0, int(round((_child_cpu_seconds() - child_cpu_start) * 1000)))
        payload = _report_payload(results, config["STROKESENSE_JOB_ID"])
        # Validate and publish bounded media before writing even the small
        # timing sidecar. Invalid galleries therefore leave no S3 artifacts.
        _publish_media(s3, bucket, report_key, results)
        timing = {
            "schema_version": 1,
            "job_id": config["STROKESENSE_JOB_ID"],
            "analysis_wall_ms": analysis_wall_ms,
            "cpu_time_ms": cpu_time_ms,
            "worker_wall_ms": int(round((time.perf_counter() - worker_start) * 1000)),
        }
        if video_duration_ms is not None:
            timing["video_duration_ms"] = video_duration_ms
        # Small sidecar lets the API persist timing without downloading the
        # potentially 32 MB report. The verified report is still committed LAST.
        s3.put_object(
            Bucket=bucket, Key=report_key[:-len("report.json")] + "runtime-metrics.json",
            Body=json.dumps(timing, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256", CacheControl="private, no-store",
        )
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
