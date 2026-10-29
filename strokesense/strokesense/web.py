"""Local-only, dependency-free browser UI for registered StrokeSense jobs.

This is deliberately not a public web service. Every request is Host/Origin
restricted; queue writes require a per-process anti-CSRF token. Report retrieval
is revalidated against the job's trusted results root.
"""
from __future__ import annotations

import argparse
import csv
import io
import hashlib
from email import policy
from email.parser import BytesParser
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from .evidence import verify_evidence_snapshot
from .jobs import JobError, JobQueue, MAX_MEDIA_BYTES
from .media import plausible_container
from .evidence import validate_public_evidence_snapshot
from .strokes import FAULTS  # fixed, deterministic candidate-fault catalogue
from .web_style import PAGE_CSS
from .registry import (DEFAULT_DB, RegistryError, analysis_permission_granted,
                       list_clips, register_clip, revoke_clip)


_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_FORM = 2048
_MAX_VIDEO_BYTES = 150 * 1024 * 1024
_MAX_UPLOAD = _MAX_VIDEO_BYTES + 1024 * 1024  # Bounded multipart fields/headers
_VIDEO_EXTENSIONS = frozenset({'.mp4', '.mov', '.mkv', '.avi', '.webm'})
_CAMERA_CHOICES = frozenset({"", "side-on", "bow-on", "stern-on"})
_MAX_REPORT = 32 * 1024 * 1024
_MAX_METRICS = 16 * 1024 * 1024
_MAX_LINKED_STROKES_PER_FINDING = 50
_MAX_SEEK_SECONDS = 120  # Keep local playback links within the Alpha clip cap.
_SEEK_TIME = re.compile(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,3})?\Z')
_RETRYABLE_JOB_ERRORS = frozenset({"analysis_failed", "interrupted", "output_unavailable"})
_PAGE_CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
             "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
_REPORT_CSP = ("sandbox; default-src 'none'; img-src data:; "
               "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
_STATUS_CSP = _PAGE_CSP + "; media-src 'self'"


def _document(title: str, content: str, *, refresh: bool = False) -> bytes:
    """Render a self-contained private analysis workspace; preserve CSP and escaping."""
    safe_title = html.escape(title, quote=True)
    meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'{meta}<title>{safe_title}</title><style>{PAGE_CSS}</style></head>'
        '<body><a class="skip-link" href="#content">Skip to content</a>'
        '<header class="topbar"><div class="topbar-inner">'
        '<a class="brand" href="/" aria-label="StrokeSense home">'
        '<span class="brand-mark" aria-hidden="true">\u224b</span>'
        'Stroke<span class="brand-accent">Sense</span></a>'
        '<nav aria-label="Primary navigation">'
        '<a href="/#upload-clip">New analysis</a>'
        '<a href="/#recent-analyses">Recent results</a></nav>'
        '<span class="local-pill">Private on this device</span>'
        '</div></header><div class="workspace">'
        '<div class="hero"><div class="eyebrow">ROWING INTELLIGENCE '
        '<span>/ LOCAL ALPHA</span></div>'
        f'<h1>{safe_title}</h1>'
        '<p>Technique patterns and the video evidence behind them, '
        'all in one private workspace.</p></div>'
        f'<main id="content" class="content-surface">{content}</main>'
        '<footer><strong>StrokeSense Alpha</strong> &middot; '
        'Local analysis only. Candidate faults are not coach-verified '
        'and generated coaching remains withheld without approval.'
        '</footer></div></body></html>'
    ).encode("utf-8")


def _seek_query(query: str) -> str | None:
    """Allow only one small, unambiguous playback timestamp parameter."""
    if not query:
        return None
    if len(query) > 64:
        raise ValueError("seek query too long")
    params = parse_qs(query, keep_blank_values=True, max_num_fields=1,
                      strict_parsing=True)
    if (set(params) != {"at"} or len(params["at"]) != 1
            or _SEEK_TIME.fullmatch(params["at"][0]) is None
            or float(params["at"][0]) > _MAX_SEEK_SECONDS):
        raise ValueError("invalid seek position")
    return params["at"][0]


def _fault_query(query: str) -> str:
    """Restrict HTML evidence filters to one known candidate-fault code."""
    if not query:
        return ""
    if len(query) > 128:
        raise ValueError("fault filter query too long")
    params = parse_qs(query, keep_blank_values=True, max_num_fields=1,
                      strict_parsing=True)
    if (set(params) != {"fault"} or len(params["fault"]) != 1
            or params["fault"][0] not in FAULTS):
        raise ValueError("invalid candidate fault filter")
    return params["fault"][0]


def _spreadsheet_text(value: str) -> str:
    """Keep user-controlled labels from becoming CSV spreadsheet formulas."""
    if value.lstrip().startswith(("=", "+", "-", "@", "\u2212")):
        return "'" + value
    return value


def _history_filters(query: str) -> tuple[str, str, str]:
    """Parse one bounded, fail-closed set of browser/history CSV filters."""
    if len(query) > 128:
        raise ValueError("history filter too long")
    params = parse_qs(query, keep_blank_values=True, max_num_fields=3,
                      strict_parsing=True)
    camera = params.get("camera", [""])[0]
    status = params.get("status", [""])[0]
    clip = params.get("clip", [""])[0]
    if (not set(params).issubset({"camera", "status", "clip"})
            or any(len(values) != 1 for values in params.values())
            or camera not in {"", "side-on", "bow-on", "stern-on", "unspecified"}
            or status not in {"", "queued", "running", "succeeded", "failed"}
            or (clip and re.fullmatch(r"[0-9a-f]{64}", clip) is None)):
        raise ValueError("invalid history filter")
    return camera, status, clip


def _visible_history(rows, camera_by_clip, camera_filter, status_filter,
                     clip_filter):
    """Apply identical local permission-scoped filters to HTML and CSV."""
    return [
        row for row in rows
        if (_JOB_ID.fullmatch(row["job_id"])
            and row["clip_id"] in camera_by_clip
            and (not camera_filter or camera_by_clip[row["clip_id"]] == camera_filter)
            and (not status_filter or row["status"] == status_filter)
            and (not clip_filter or row["clip_id"] == clip_filter))
    ]


def _allowed_methods(route: str) -> str | None:
    """HTTP Allow for known local endpoints; unknown routes stay 404."""
    if (route in ("/", "/api/jobs", "/history.csv", "/compare", "/compare.csv") or route.startswith("/api/jobs/")
            or route.startswith("/jobs/") or route.startswith("/reports/")
            or route.startswith("/media/")):
        return "GET"
    if route in ("/jobs", "/upload", "/revoke"):
        return "POST"
    return None


def create_server(
    jobs: JobQueue, *, registry_db, host: str = "127.0.0.1", port: int = 0,
    upload_dir=None,
) -> ThreadingHTTPServer:
    """Return an explicit loopback-only server; caller owns its lifecycle."""
    if host != "127.0.0.1":
        raise ValueError("local UI can bind only to 127.0.0.1")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid HTTP port")
    token = secrets.token_urlsafe(32)
    registry_path = Path(registry_db).expanduser().resolve()
    result_root = jobs._results_root.resolve()  # Trusted local JobQueue directory.
    private_uploads = Path(upload_dir if upload_dir is not None
                           else result_root.parent / "uploads").expanduser().resolve()

    def permitted_recent_jobs():
        """Only display job links for clips currently permitted locally."""
        return [
            row for row in jobs.list_recent(limit=20)
            if (analysis_permission_granted(row["clip_id"], registry_path)
                and row.get("coaching_state") == "withheld")
        ]

    def verified_media_available(job_id: str) -> bool:
        """Only offer navigation to a real, unchanged, bounded job-owned clip.

        This never returns media bytes or a private location to the browser.
        The /media route independently verifies again at playback time.
        """
        try:
            artifact = jobs.media_artifact(job_id)
            if artifact is None:
                return False
            raw, expected_digest = artifact
            if not isinstance(raw, str) or not isinstance(expected_digest, str):
                return False
            rel = Path(raw)
            if (rel.is_absolute() or not rel.parts or rel.parts[0] != job_id
                    or ".." in rel.parts or
                    rel.suffix.lower() not in (".mp4", ".webm")):
                return False
            job_root = (result_root / job_id).resolve(strict=True)
            target = (result_root / rel).resolve(strict=True)
            if not target.is_file() or not target.is_relative_to(job_root):
                return False
            digest = hashlib.sha256()
            size = 0
            with target.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_MEDIA_BYTES:
                        return False
                    digest.update(chunk)
            return hmac.compare_digest(expected_digest, digest.hexdigest())
        except (OSError, ValueError, TypeError):
            return False
        except Exception:
            # Private storage failures must not expose paths or stack traces.
            return False

    def verified_comparison_summary(job_id: str):
        """Recheck both job-owned artifacts before comparing saved observations.

        The digest confirms consistency with the saved job, not real-world
        accuracy or genuine approval of heuristic candidate faults.
        """
        try:
            record = jobs.get(job_id)
            if record is None or record["status"] != "succeeded":
                return 404, None
            if not analysis_permission_granted(record["clip_id"], registry_path):
                return 403, None
            if record.get("coaching_state") != "withheld":
                return 409, None
            raw = record.get("report_path")
            if not isinstance(raw, str):
                return 404, None
            relative = Path(raw)
            if (relative.is_absolute() or not relative.parts
                    or relative.parts[0] != job_id or ".." in relative.parts
                    or relative.name != "report.html"):
                return 404, None
            job_root = (result_root / job_id).resolve(strict=True)
            report = (result_root / relative).resolve(strict=True)
            if (not job_root.is_relative_to(result_root)
                    or not report.is_file() or not report.is_relative_to(job_root)):
                return 409, None
            if report.stat().st_size > _MAX_REPORT:
                return 413, None
            report_hash = hashlib.sha256()
            byte_count = 0
            with report.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > _MAX_REPORT:
                        return 413, None
                    report_hash.update(chunk)
            expected_report = jobs.report_sha256(job_id)
            if (not isinstance(expected_report, str)
                    or not hmac.compare_digest(expected_report,
                                               report_hash.hexdigest())):
                return 409, None
            metrics = (report.parent / "metrics.json").resolve(strict=True)
            if (metrics.name != "metrics.json" or not metrics.is_file()
                    or not metrics.is_relative_to(job_root)):
                return 409, None
            if metrics.stat().st_size > _MAX_METRICS:
                return 413, None
            with metrics.open("rb") as handle:
                raw_metrics = handle.read(_MAX_METRICS + 1)
            if len(raw_metrics) > _MAX_METRICS:
                return 413, None
            expected_metrics = jobs.metrics_sha256(job_id)
            if (not isinstance(expected_metrics, str)
                    or not hmac.compare_digest(
                        expected_metrics, hashlib.sha256(raw_metrics).hexdigest()
                    )):
                return 409, None
            data = json.loads(raw_metrics.decode("utf-8"))
            snapshot = data.get("evidence") if isinstance(data, dict) else None
            if not validate_public_evidence_snapshot(snapshot):
                return 409, None
            analyzed = sum(seat["analyzed_strokes"] for seat in snapshot["seats"])
            counts = {}
            for finding in snapshot["findings"]:
                code = finding["fault_code"]
                counts[code] = counts.get(code, 0) + finding["observed_count"]
            if any(value > analyzed for value in counts.values()):
                return 409, None
            current_clip = next((
                clip for clip in list_clips(registry_path)
                if (clip["clip_id"] == record["clip_id"]
                    and clip["permission"] == "granted")
            ), None)
            if current_clip is None:
                return 403, None
            camera = current_clip.get("camera")
            if camera not in {"side-on", "bow-on", "stern-on"}:
                camera = "unspecified"
            return 200, {
                "analyzed": analyzed, "counts": counts,
                "clip_id": record["clip_id"], "camera": camera,
            }
        except FileNotFoundError:
            # Historical results may not include versioned evidence.
            return 404, None
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return 409, None
        except Exception:
            return 503, None

    class Handler(BaseHTTPRequestHandler):
        server_version = "StrokeSense"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Do not emit clip IDs, private paths or raw user-supplied routes.
            pass

        def _send(self, code, data: bytes, *, mime="text/html; charset=utf-8",
                  csp=_PAGE_CSP, location=None, allow=None,
                  content_range=None, accept_ranges=False, download_name=None):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            if accept_ranges:
                self.send_header("Accept-Ranges", "bytes")
            if content_range is not None:
                self.send_header("Content-Range", content_range)
            if location is not None:
                self.send_header("Location", location)
            if allow is not None:
                self.send_header("Allow", allow)
            if download_name is not None:
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{download_name}"')
            self.end_headers()
            # RFC 9110: HEAD responses must contain no message body.
            if data and self.command != "HEAD":
                self.wfile.write(data)

        def _error(self, status, *, allow=None):
            if urlsplit(self.path).path.startswith("/api/"):
                # Safe, machine-readable Problem Details for local API clients.
                # Never include exceptions, filesystem paths or request contents.
                title = {
                    400: "Bad Request",
                    403: "Forbidden",
                    404: "Not Found",
                    405: "Method Not Allowed",
                    409: "Conflict",
                    413: "Content Too Large",
                    415: "Unsupported Media Type",
                    422: "Unprocessable Content",
                    503: "Service Unavailable",
                }.get(status, "Request Failed")
                body = json.dumps(
                    {"type": "about:blank", "title": title, "status": status},
                    sort_keys=True,
                ).encode("utf-8")
                self._send(status, body, mime="application/problem+json",
                           allow=allow)
                return
            self._send(status, _document("Request unavailable",
                                         "<p>The requested action is unavailable.</p>"),
                       allow=allow)

        def _trusted_request(self):
            hosts = self.headers.get_all("Host") or []
            port_now = self.server.server_address[1]
            accepted = {f"127.0.0.1:{port_now}", f"localhost:{port_now}"}
            if len(hosts) != 1 or hosts[0] not in accepted:
                return False
            origins = self.headers.get_all("Origin") or []
            if len(origins) > 1 or (origins and origins[0] != f"http://{hosts[0]}"):
                return False
            return True

        def _home(self, *, camera_filter="", status_filter="", clip_filter=""):
            try:
                clips = [c for c in list_clips(registry_path)
                         if c["permission"] == "granted"]
            except Exception:
                self._error(503)
                return
            if clip_filter and clip_filter not in {c["clip_id"] for c in clips}:
                self._error(400)
                return
            options = "".join(
                '<option value="' + html.escape(c["clip_id"], quote=True) + '">'
                + html.escape(c["clip_id"]) + " — "
                + html.escape(c.get("camera") or "camera unspecified")
                + '</option>' for c in clips
            )
            if options:
                controls = (
                    '<form method="post" action="/jobs">'
                    '<label>Registered clip <select name="clip_id">' + options
                    + '</select></label><input type="hidden" name="csrf" value="'
                    + html.escape(token, quote=True)
                    + '"><button type="submit">Analyze clip</button></form>'
                    + '<form method="post" action="/revoke">'
                    + '<label>Withdraw permission for clip <select name="clip_id">'
                    + options + '</select></label>'
                    + '<input type="hidden" name="csrf" value="'
                    + html.escape(token, quote=True)
                    + '"><button type="submit">Withdraw analysis permission</button>'
                    + '</form>'
                )
            else:
                controls = ("<p>No permission-claimed clips are registered. "
                            "Use the private import form below or the registry CLI.</p>")
            try:
                recent = permitted_recent_jobs()
            except Exception:
                self._error(503)
                return
            # Reuse the already permission-filtered public clip labels.
            # Never use local source paths or rights provenance for history.
            camera_by_clip = {
                clip["clip_id"]: clip.get("camera") or "unspecified"
                for clip in clips
            }
            history_items = "".join(
                '<li><a href="/jobs/' + html.escape(row["job_id"], quote=True)
                + '">Analysis ' + html.escape(row["job_id"][:12])
                + '</a> — ' + html.escape(row["status"])
                + ' — camera: '
                + html.escape(str(camera_by_clip.get(row["clip_id"], "unspecified")))
                + (' — <a href="/reports/'
                   + html.escape(row["job_id"], quote=True)
                   + '">Open technique report</a>'
                   if row["status"] == "succeeded" else "")
                + ' — coaching: withheld</li>'
                for row in _visible_history(
                    recent, camera_by_clip, camera_filter, status_filter,
                    clip_filter,
                )
            )
            camera_options = (("", "All"), ("side-on", "Side-on"),
                              ("bow-on", "Bow-on"), ("stern-on", "Stern-on"),
                              ("unspecified", "Unspecified"))
            camera_select = "".join(
                '<option value="' + value + '"'
                + (' selected' if value == camera_filter else '')
                + '>' + label + '</option>'
                for value, label in camera_options
            )
            status_options = (("", "All"), ("queued", "Queued"),
                              ("running", "Running"),
                              ("succeeded", "Succeeded"), ("failed", "Failed"))
            status_select = "".join(
                '<option value="' + value + '"'
                + (' selected' if value == status_filter else '')
                + '>' + label + '</option>'
                for value, label in status_options
            )
            clip_select = '<option value="">All clips</option>' + "".join(
                '<option value="' + html.escape(c["clip_id"], quote=True) + '"'
                + (' selected' if c["clip_id"] == clip_filter else '')
                + '>' + html.escape(c["clip_id"][:12]) + " — "
                + html.escape(c.get("camera") or "unspecified")
                + '</option>' for c in clips
            )
            history_q = urlencode([
                (field, value) for field, value in (
                    ("camera", camera_filter), ("status", status_filter),
                    ("clip", clip_filter),
                ) if value
            ])
            history_csv_link = "/history.csv" + ("?" + history_q if history_q else "")
            history = ('<h2 id="recent-analyses">Recent analyses</h2>'
                       '<form method="get" action="/">'
                       '<label>Filter analyses by camera <select name="camera">'
                       + camera_select + '</select></label>'
                       '<label>Filter analyses by status <select name="status">'
                       + status_select + '</select></label>'
                       '<label>Filter analyses by clip <select name="clip">'
                       + clip_select + '</select></label>'
                       '<button type="submit">Filter</button></form>'
                       '<p><a href="/">Clear filters</a></p>'
                       '<p><a href="' + html.escape(history_csv_link, quote=True)
                       + '">Download analysis history CSV</a>'
                       ' (current filters, up to 20 permission-allowed jobs)</p>'
                       + ('<ol>' + history_items + '</ol>' if history_items
                          else '<p>None yet.</p>'))
            upload_form = (
                '<h2 id="upload-clip">Register a new local clip</h2>'
                '<form method="post" action="/upload" enctype="multipart/form-data">'
                '<label>Video (up to 150 MiB; .mp4, .mov, .mkv, .avi, .webm): '
                '<input type="file" name="video" required></label>'
                '<label>Permission attestation: '
                '<input type="checkbox" name="permission" value="granted" required>'
                'I attest I have permission to analyze this recording</label>'
                '<label>Permission source / provenance: '
                '<input type="text" name="provenance" maxlength="256" required></label>'
                '<label>Camera viewpoint (optional): <select name="camera">'
                '<option value="">Unspecified</option>'
                '<option value="side-on">Side-on</option>'
                '<option value="bow-on">Bow-on</option>'
                '<option value="stern-on">Stern-on</option>'
                '</select></label>'
                '<label><input type="checkbox" name="analyze" value="now" checked>'
                ' Analyze immediately after import</label>'
                '<input type="hidden" name="csrf" value="'
                + html.escape(token, quote=True)
                + '"><button type="submit">Import locally</button></form>'
            )
            comparable = [
                row for row in recent
                if (row["status"] == "succeeded"
                    and _JOB_ID.fullmatch(row["job_id"])
                    and row["clip_id"] in camera_by_clip)
            ]
            comparison_form = ""
            if len(comparable) >= 2:
                older, newer = comparable[1]["job_id"], comparable[0]["job_id"]

                def comparison_options(selected):
                    return "".join(
                        '<option value="' + html.escape(row["job_id"], quote=True)
                        + '"' + (' selected' if row["job_id"] == selected else '')
                        + '>Analysis ' + html.escape(row["job_id"][:12])
                        + '</option>' for row in comparable
                    )

                comparison_form = (
                    '<h2>Compare saved analyses</h2>'
                    '<form method="get" action="/compare">'
                    '<label>Earlier run <select name="before">'
                    + comparison_options(older) + '</select></label>'
                    '<label>Later run <select name="after">'
                    + comparison_options(newer) + '</select></label>'
                    '<button type="submit">Compare candidate faults</button></form>'
                    '<p>Only runs with saved validated evidence can be compared. '
                    'These are unreviewed candidate detections, not measured '
                    'coaching effectiveness.</p>'
                )
            body = ("<p>Local prototype. Permission is an operator assertion, "
                    "not independent consent verification. Analysis runs on "
                    "your computer. No generated LLM advice is released here.</p>"
                    + controls + upload_form + history + comparison_form)
            self._send(200, _document("StrokeSense local Alpha", body))


        def _compare(self, query: str, *, as_csv=False):
            """Side-by-side candidate counts from two independently checked runs."""
            if len(query) > 128:
                self._error(400)
                return
            try:
                params = parse_qs(query, keep_blank_values=True,
                                  max_num_fields=2, strict_parsing=True)
                if (set(params) != {"before", "after"}
                        or any(len(values) != 1 for values in params.values())):
                    raise ValueError("invalid comparison selection")
                before, after = params["before"][0], params["after"][0]
                if (before == after or _JOB_ID.fullmatch(before) is None
                        or _JOB_ID.fullmatch(after) is None):
                    raise ValueError("invalid comparison identifiers")
            except ValueError:
                self._error(400)
                return
            first_code, first = verified_comparison_summary(before)
            if first_code != 200:
                self._error(first_code)
                return
            last_code, last = verified_comparison_summary(after)
            if last_code != 200:
                self._error(last_code)
                return
            faults = sorted(set(first["counts"]) | set(last["counts"]))
            if as_csv:
                output = io.StringIO(newline="")
                writer = csv.writer(output, lineterminator="\r\n")
                writer.writerow((
                    "fault_code", "before_job_id", "before_flagged",
                    "before_analyzed", "after_job_id", "after_flagged",
                    "after_analyzed",
                ))
                for code in faults:
                    values = (
                        code, before, first["counts"].get(code, 0),
                        first["analyzed"], after, last["counts"].get(code, 0),
                        last["analyzed"],
                    )
                    writer.writerow([
                        _spreadsheet_text(str(value)) for value in values
                    ])
                self._send(
                    200, output.getvalue().encode("utf-8"),
                    mime="text/csv; charset=utf-8",
                    download_name="strokesense-comparison.csv",
                )
                return
            table_rows = []
            for code in faults:
                def rate(summary, job_id):
                    n = summary["analyzed"]
                    if n == 0:
                        label = "insufficient evidence (0 analyzed strokes)"
                    else:
                        label = (
                            f'{summary["counts"].get(code, 0)} of {n} analyzed strokes'
                        )
                    # Both the job ID and fault code have already passed
                    # independent evidence/schema validation above.
                    target = ("/jobs/" + job_id + "/evidence?fault="
                              + html.escape(code, quote=True))
                    return ('<a href="' + target + '">'
                            + html.escape(label) + '</a>')
                table_rows.append(
                    '<tr><th scope="row">' + html.escape(code) + '</th><td>'
                    + rate(first, before) + '</td><td>'
                    + rate(last, after) + '</td></tr>'
                )
            if table_rows:
                frequency = (
                    '<table border="1"><thead><tr><th>Candidate fault</th>'
                    '<th>Earlier run</th><th>Later run</th></tr></thead><tbody>'
                    + "".join(table_rows) + '</tbody></table>'
                )
            else:
                frequency = (
                    "<p>Neither saved evidence snapshot flagged a candidate "
                    "fault. This is not a negative coach-reviewed label.</p>"
                )
            same_clip = first["clip_id"] == last["clip_id"]
            content = (
                "<p>Candidate fault counts over analyzed strokes only; "
                "not proof of improvement, diagnostic accuracy, or coaching "
                "effectiveness. Different footage, viewpoints and settings "
                "can make these runs incomparable.</p>"
                + ("<p>Same registered source clip.</p>" if same_clip
                   else "<p>Different registered source clips.</p>")
                + "<p>Earlier viewpoint (operator-entered): "
                + html.escape(first["camera"]) + "</p>"
                + "<p>Later viewpoint (operator-entered): "
                + html.escape(last["camera"]) + "</p>"
                + ("<p><strong>Camera viewpoints differ.</strong> "
                   "Candidate counts are not normalized across viewpoints.</p>"
                   if first["camera"] != last["camera"] else "")
                + "<p>Coaching withheld on both analyses.</p>"
                + '<p>Earlier: <a href="/reports/' + before
                + '">Open report</a> · <a href="/jobs/' + before
                + '/evidence">Inspect evidence</a></p>'
                + '<p>Later: <a href="/reports/' + after
                + '">Open report</a> · <a href="/jobs/' + after
                + '/evidence">Inspect evidence</a></p>'
                + frequency
                + '<p><a href="'
                + html.escape(
                    "/compare.csv?" + urlencode((("before", before), ("after", after))),
                    quote=True,
                )
                + '">Download comparison CSV</a></p>'
                + '<p><a href="/">Back to analysis library</a></p>'
            )
            self._send(200, _document("Compare saved analyses", content))

        def _history_csv(self, *, camera_filter="", status_filter="",
                         clip_filter=""):
            """Export only the bounded public history already visible locally."""
            try:
                clips = [c for c in list_clips(registry_path)
                         if c["permission"] == "granted"]
                camera_by_clip = {
                    c["clip_id"]: c.get("camera") or "unspecified"
                    for c in clips
                }
                if clip_filter and clip_filter not in camera_by_clip:
                    self._error(400)
                    return
                selected = _visible_history(
                    permitted_recent_jobs(), camera_by_clip, camera_filter,
                    status_filter, clip_filter,
                )
            except Exception:
                self._error(503)
                return
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\r\n")
            writer.writerow((
                "job_id", "clip_id", "camera", "status", "created_utc",
                "finished_utc", "coaching_state", "report_available",
            ))
            for row in selected:
                values = (
                    row["job_id"], row["clip_id"],
                    camera_by_clip[row["clip_id"]], row["status"],
                    row["created_utc"], row["finished_utc"],
                    "withheld", "yes" if row["status"] == "succeeded" else "no",
                )
                writer.writerow([
                    _spreadsheet_text("" if value is None else str(value))
                    for value in values
                ])
            self._send(
                200, output.getvalue().encode("utf-8"),
                mime="text/csv; charset=utf-8",
                download_name="strokesense-history.csv",
            )

        def _status(self, job_id: str, *, api=False, at=None):
            if not _JOB_ID.fullmatch(job_id):
                self._error(404)
                return
            try:
                record = jobs.get(job_id)
            except Exception:
                self._error(503)
                return
            if record is None:
                self._error(404)
                return
            try:
                permitted = analysis_permission_granted(
                    record["clip_id"], registry_path
                )
            except Exception:
                self._error(503)
                return
            if not permitted:
                self._error(403)
                return
            # This Alpha has no verified, persisted LLM release pathway.
            # Do not trust an unexpected (including tampered 'released') flag.
            if record.get("coaching_state") != "withheld":
                self._error(409)
                return
            if api:
                body = json.dumps(record, sort_keys=True).encode("utf-8")
                self._send(200, body, mime="application/json; charset=utf-8")
                return
            status = html.escape(record["status"])
            err = record.get("error_code")
            message = f'<p>Error: <code>{html.escape(err)}</code></p>' if err else ""
            link = (f'<p><a href="/reports/{job_id}">Open technique report</a></p>'
                    f'<p><a href="/jobs/{job_id}/evidence">Inspect saved evidence</a>'
                    ' (generated coaching withheld)</p>'
                    if status == "succeeded" else "")
            retry = ""
            if status == "failed" and err in _RETRYABLE_JOB_ERRORS:
                # Reuse the existing CSRF-protected POST /jobs; a retry is a
                # *new* job, never a mutation of the original failed record.
                retry = (
                    '<form method="post" action="/jobs">'
                    '<input type="hidden" name="clip_id" value="'
                    + html.escape(record["clip_id"], quote=True)
                    + '"><input type="hidden" name="csrf" value="'
                    + html.escape(token, quote=True)
                    + '"><button type="submit">Retry analysis</button></form>'
                )
            media_player = ""
            if status == "succeeded":
                try:
                    media = jobs.media_artifact(job_id)
                except Exception:
                    self._error(503)
                    return
                if media is not None:
                    mime = ("video/webm" if media[0].lower().endswith(".webm")
                            else "video/mp4")
                    fragment = f"#t={at}" if at is not None else ""
                    media_player = (
                        '<h2>Annotated video</h2><video controls preload="metadata" '
                        f'width="720" src="/media/{job_id}{fragment}" type="{mime}">'
                        'Your browser does not support HTML5 video.</video>'
                    )
            if at is not None and not media_player:
                self._error(404)
                return
            state_token = status if status in ("queued", "running", "succeeded", "failed") else "unknown"
            content = (f"<p>Job: <code>{job_id}</code></p>"
                       f'<p>Status: <span class="state-badge state-{state_token}" role="status">{status}</span></p>'
                       '<p>Coaching: <strong>withheld</strong></p>'
                       + message + link + media_player + retry
                       + '<p><a href="/">Choose another clip</a></p>')
            self._send(200, _document("Analysis status", content,
                                      refresh=status in ("queued", "running")),
                       csp=_STATUS_CSP)

        def _media(self, job_id: str):
            """Serve only verified, bounded, local job-owned rendered media."""
            if not _JOB_ID.fullmatch(job_id):
                self._error(404)
                return
            try:
                record = jobs.get(job_id)
                if record is None or record["status"] != "succeeded":
                    self._error(404)
                    return
                if not analysis_permission_granted(record["clip_id"], registry_path):
                    self._error(403)
                    return
                if record.get("coaching_state") != "withheld":
                    self._error(409)
                    return
                artifact = jobs.media_artifact(job_id)
                if artifact is None:
                    self._error(404)
                    return
                raw, expected_digest = artifact
                rel = Path(raw)
                if (rel.is_absolute() or not rel.parts or rel.parts[0] != job_id
                        or ".." in rel.parts or
                        rel.suffix.lower() not in (".mp4", ".webm")):
                    self._error(404)
                    return
                job_root = (result_root / job_id).resolve(strict=True)
                target = (result_root / rel).resolve(strict=True)
                if not target.is_file() or not target.is_relative_to(job_root):
                    self._error(404)
                    return
                with target.open("rb") as handle:
                    payload = handle.read(MAX_MEDIA_BYTES + 1)
                if len(payload) > MAX_MEDIA_BYTES:
                    self._error(413)
                    return
                if (not isinstance(expected_digest, str) or
                        not hmac.compare_digest(
                            expected_digest, hashlib.sha256(payload).hexdigest())):
                    self._error(409)
                    return
            except (OSError, ValueError, TypeError):
                self._error(404)
                return
            except Exception:
                self._error(503)
                return
            mime = "video/webm" if rel.suffix.lower() == ".webm" else "video/mp4"
            ranges = self.headers.get_all("Range") or []
            if not ranges:
                self._send(200, payload, mime=mime, accept_ranges=True)
                return
            total = len(payload)
            invalid = (len(ranges) != 1 or len(ranges[0]) > 128 or
                       not re.fullmatch(r"bytes=(?:[0-9]{0,12})-(?:[0-9]{0,12})",
                                        ranges[0]))
            start = end = 0
            if not invalid:
                first, last = ranges[0][len("bytes="):].split("-", 1)
                if not first and not last:
                    invalid = True
                elif first:
                    start = int(first)
                    end = min(int(last), total - 1) if last else total - 1
                    invalid = start > end or start >= total
                else:
                    suffix = int(last)
                    invalid = suffix < 1 or total == 0
                    if not invalid:
                        start = max(total - suffix, 0)
                        end = total - 1
            if invalid:
                self._send(416, b"", mime=mime, accept_ranges=True,
                           content_range=f"bytes */{total}")
                return
            self._send(206, payload[start:end + 1], mime=mime,
                       accept_ranges=True,
                       content_range=f"bytes {start}-{end}/{total}")

        def _report(self, job_id: str):
            if not _JOB_ID.fullmatch(job_id):
                self._error(404)
                return
            try:
                record = jobs.get(job_id)
                if record and not analysis_permission_granted(
                    record["clip_id"], registry_path
                ):
                    self._error(403)
                    return
                if not record or record["status"] != "succeeded":
                    self._error(404)
                    return
                # Persisted release flags are not authority to publish coaching.
                # There is no independently verified release path in this Alpha.
                if record.get("coaching_state") != "withheld":
                    self._error(409)
                    return
                raw = record.get("report_path")
                if not isinstance(raw, str):
                    self._error(404)
                    return
                rel = Path(raw)
                if (rel.is_absolute() or not rel.parts or rel.parts[0] != job_id
                        or ".." in rel.parts or rel.name != "report.html"):
                    self._error(404)
                    return
                target = (result_root / rel).resolve(strict=True)
                job_root = (result_root / job_id).resolve(strict=True)
                if not target.is_file() or not target.is_relative_to(job_root):
                    self._error(404)
                    return
                if target.stat().st_size > _MAX_REPORT:
                    self._error(413)
                    return
                # File may grow after the size check; cap bytes actually read.
                with target.open("rb") as stream:
                    data = stream.read(_MAX_REPORT + 1)
                if len(data) > _MAX_REPORT:
                    self._error(413)
                    return
                # The recorded success must attest to these exact HTML bytes.
                expected_digest = jobs.report_sha256(job_id)
                if (not isinstance(expected_digest, str)
                        or not hmac.compare_digest(
                            expected_digest, hashlib.sha256(data).hexdigest()
                        )):
                    self._error(409)
                    return
            except (OSError, ValueError, TypeError):
                self._error(404)
                return
            except Exception:
                self._error(503)
                return
            self._send(200, data, csp=_REPORT_CSP)


        def _evidence(self, job_id: str, *, api=False, as_csv=False,
                      review_template=False, fault_template=False,
                      fault_filter=""):
            if not _JOB_ID.fullmatch(job_id):
                self._error(404)
                return
            try:
                record = jobs.get(job_id)
                if record and not analysis_permission_granted(
                    record["clip_id"], registry_path
                ):
                    self._error(403)
                    return
                if not record or record["status"] != "succeeded":
                    self._error(404)
                    return
                # Persisted release flags are not authority to publish coaching.
                # There is no independently verified release path in this Alpha.
                if record.get("coaching_state") != "withheld":
                    self._error(409)
                    return
                raw = record.get("report_path")
                if not isinstance(raw, str):
                    self._error(404)
                    return
                report_rel = Path(raw)
                if (report_rel.is_absolute() or not report_rel.parts
                        or report_rel.parts[0] != job_id
                        or ".." in report_rel.parts
                        or report_rel.name != "report.html"):
                    self._error(404)
                    return
                job_root = (result_root / job_id).resolve(strict=True)
                report = (result_root / report_rel).resolve(strict=True)
                if not report.is_file() or not report.is_relative_to(job_root):
                    self._error(404)
                    return
                if report.stat().st_size > _MAX_REPORT:
                    self._error(413)
                    return
                with report.open("rb") as stream:
                    verified_report = stream.read(_MAX_REPORT + 1)
                if len(verified_report) > _MAX_REPORT:
                    self._error(413)
                    return
                expected_digest = jobs.report_sha256(job_id)
                if (not isinstance(expected_digest, str)
                        or not hmac.compare_digest(
                            expected_digest, hashlib.sha256(verified_report).hexdigest()
                        )):
                    self._error(409)
                    return
                metrics = (report.parent / "metrics.json").resolve(strict=True)
                if (metrics.name != "metrics.json" or not metrics.is_file()
                        or not metrics.is_relative_to(job_root)):
                    self._error(404)
                    return
                if metrics.stat().st_size > _MAX_METRICS:
                    self._error(413)
                    return
                # Do not rely solely on a possibly stale stat() result.
                with metrics.open("rb") as stream:
                    metrics_bytes = stream.read(_MAX_METRICS + 1)
                if len(metrics_bytes) > _MAX_METRICS:
                    self._error(413)
                    return
                # A rehashed snapshot alone cannot attest to the bytes
                # saved at analysis completion; bind them to the job record.
                expected_metrics = jobs.metrics_sha256(job_id)
                if (not isinstance(expected_metrics, str)
                        or not hmac.compare_digest(
                            expected_metrics,
                            hashlib.sha256(metrics_bytes).hexdigest(),
                        )):
                    self._error(409)
                    return
                data = json.loads(metrics_bytes.decode("utf-8"))
                snapshot = data.get("evidence") if isinstance(data, dict) else None
                if not validate_public_evidence_snapshot(snapshot):
                    self._error(409)
                    return
                columns = {
                    "seats": ("id", "seat", "analyzed_strokes", "status"),
                    "strokes": ("id", "seat_id", "index", "catch_frame",
                                "finish_frame", "next_catch_frame", "catch_seconds",
                                "finish_seconds", "next_catch_seconds", "fault_codes"),
                    "findings": ("id", "seat_id", "fault_code", "stroke_ids",
                                 "observed_count", "analyzed_strokes",
                                 "observed_fraction", "eligible_strokes",
                                 "status", "coaching_eligible"),
                }
                curated = {key: snapshot[key] for key in
                           ("schema_version", "analysis_id", "fps",
                            "start_seconds", "status")}
                for collection, fields in columns.items():
                    values = snapshot.get(collection)
                    if not isinstance(values, list) or len(values) > 5000:
                        raise ValueError("invalid evidence collection")
                    curated[collection] = [
                        {key: row[key] for key in fields if key in row}
                        for row in values if isinstance(row, dict)
                    ]
                    if len(curated[collection]) != len(values):
                        raise ValueError("invalid evidence entry")
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                self._error(409)
                return
            except Exception:
                self._error(503)
                return
            if as_csv or review_template or fault_template:
                output = io.StringIO(newline="")
                writer = csv.writer(output, lineterminator="\r\n")
                labels = {row["id"]: row["seat"] for row in curated["seats"]}
                if fault_template:
                    # Explicit negative opportunities are required for any
                    # later valid recall estimate. Human labels stay blank.
                    has_saved_video = verified_media_available(job_id)
                    writer.writerow((
                        "schema_version", "seat_id", "seat", "stroke_id",
                        "stroke_index", "fault_code", "catch_seconds",
                        "video_seek_seconds", "predicted",
                        "coach_fault_present", "coach_comments",
                        "review_status",
                    ))
                    for stroke in curated["strokes"]:
                        seek_seconds = ""
                        if has_saved_video:
                            elapsed = (
                                stroke["catch_seconds"] - curated["start_seconds"]
                            )
                            if (math.isfinite(elapsed)
                                    and 0 <= elapsed <= _MAX_SEEK_SECONDS):
                                seek_seconds = (
                                    f"{elapsed:.3f}".rstrip("0").rstrip(".")
                                )
                        for fault_code in sorted(FAULTS):
                            writer.writerow((
                                curated["schema_version"],
                                _spreadsheet_text(stroke["seat_id"]),
                                _spreadsheet_text(labels[stroke["seat_id"]]),
                                _spreadsheet_text(stroke["id"]),
                                stroke["index"], fault_code,
                                stroke["catch_seconds"], seek_seconds,
                                int(fault_code in stroke["fault_codes"]),
                                "", "", "unreviewed",
                            ))
                elif review_template:
                    # A worksheet for future human review, not a label dataset.
                    # These review fields must never be prefilled by heuristics.
                    # Optional clip-relative navigation is derived only from
                    # the validated, saved source-relative stroke evidence.
                    has_saved_video = verified_media_available(job_id)
                    writer.writerow(("stroke_id", "seat", "stroke_index",
                                     "catch_seconds", "video_seek_seconds",
                                     "fault_codes", "coach_fault_present",
                                     "coach_comments", "review_status"))
                    for stroke in curated["strokes"]:
                        seek_seconds = ""
                        if has_saved_video:
                            elapsed = (stroke["catch_seconds"]
                                       - curated["start_seconds"])
                            if (math.isfinite(elapsed)
                                    and 0 <= elapsed <= _MAX_SEEK_SECONDS):
                                seek_seconds = (
                                    f"{elapsed:.3f}".rstrip("0").rstrip(".")
                                )
                        writer.writerow((
                            _spreadsheet_text(stroke["id"]),
                            _spreadsheet_text(labels[stroke["seat_id"]]),
                            stroke["index"], stroke["catch_seconds"],
                            seek_seconds,
                            _spreadsheet_text("; ".join(stroke["fault_codes"])),
                            "", "", "unreviewed",
                        ))
                else:
                    writer.writerow(("seat", "stroke_index", "catch_seconds",
                                     "finish_seconds", "fault_codes"))
                    for stroke in curated["strokes"]:
                        writer.writerow((
                            _spreadsheet_text(labels[stroke["seat_id"]]),
                            stroke["index"], stroke["catch_seconds"],
                            stroke["finish_seconds"],
                            "; ".join(stroke["fault_codes"]),
                        ))
                csv_bytes = output.getvalue().encode("utf-8")
                if len(csv_bytes) > _MAX_REPORT:
                    self._error(413)
                    return
                self._send(200, csv_bytes, mime="text/csv; charset=utf-8")
                return
            if api:
                response = {"coaching_state": "withheld", "evidence": curated}
                self._send(200, json.dumps(response, allow_nan=False).encode("utf-8"),
                           mime="application/json; charset=utf-8")
                return
            seats = "".join(
                "<li>" + html.escape(str(row.get("seat", "unknown")))
                + " — " + html.escape(str(row.get("status", "unknown")))
                + "</li>" for row in curated["seats"]
            )
            # Generate anchors only from trusted list positions. Source- and
            # model-provided IDs are references, not HTML attribute values.
            seat_labels = {
                row["id"]: row["seat"] for row in curated["seats"]
            }
            stroke_ref = {
                row["id"]: (f"stroke-{position}", row)
                for position, row in enumerate(curated["strokes"])
            }
            # Do not advertise dead or modified media from saved evidence.
            media_available = verified_media_available(job_id)

            def watch_link(stroke, label):
                # Source-relative evidence times are not rendered-video times:
                # exported annotated footage starts at pose.start (t=0).
                if not media_available:
                    return ""
                elapsed = stroke["catch_seconds"] - curated["start_seconds"]
                if (not math.isfinite(elapsed)
                        or not 0 <= elapsed <= _MAX_SEEK_SECONDS):
                    return ""
                second = f"{elapsed:.3f}".rstrip("0").rstrip(".")
                # The job ID and timestamp are internally validated; never
                # interpolate model/source-controlled IDs into an HTML URL.
                return (f'<a href="/jobs/{job_id}?at={second}">'
                        + html.escape(label) + '</a>')

            def stroke_item(position, row):
                watch = watch_link(row, "Watch catch")
                return (
                    '<li id="stroke-' + str(position) + '">Seat '
                    + html.escape(seat_labels.get(row["seat_id"], "unknown"))
                    + ", stroke " + html.escape(str(row["index"]))
                    + ": Catch " + html.escape(str(row["catch_seconds"]))
                    + " s; finish " + html.escape(str(row["finish_seconds"]))
                    + " s; faults: "
                    + html.escape(", ".join(str(x) for x in row["fault_codes"]))
                    + (" " + watch if watch else "") + "</li>"
                )

            strokes = "".join(
                stroke_item(position, row)
                for position, row in enumerate(curated["strokes"])
                if not fault_filter or fault_filter in row["fault_codes"]
            )

            def finding_item(row):
                ids = row["stroke_ids"]
                visible = ids[:_MAX_LINKED_STROKES_PER_FINDING]
                links = ", ".join(
                    '<a href="#' + stroke_ref[sid][0] + '">Stroke '
                    + html.escape(str(stroke_ref[sid][1]["index"])) + "</a>"
                    for sid in visible
                )
                remaining = len(ids) - len(visible)
                more = (
                    f" and {remaining} more supporting stroke"
                    + ("s" if remaining != 1 else "")
                    + " (see JSON evidence)"
                    if remaining else ""
                )
                # The snapshot validator attests that supporting IDs refer to
                # saved strokes. Their list order decides the first example.
                reference = stroke_ref.get(ids[0]) if ids else None
                watch = (watch_link(reference[1], "Watch first example")
                         if reference is not None else "")
                numerator = row["observed_count"]
                denominator = row["analyzed_strokes"]
                # Native HTML meter is a frequency among analyzed candidates,
                # not a probability of truth, classifier accuracy or confidence.
                frequency_meter = (
                    f' <meter min="0" max="{denominator}" value="{numerator}" '
                    'aria-label="Candidate frequency among analyzed strokes">'
                    f'{numerator} of {denominator}</meter>'
                    if denominator > 0
                    else " (no analyzed strokes available for frequency)"
                )
                return (
                    "<li>" + html.escape(row["fault_code"])
                    + " — " + html.escape(row["status"])
                    + " — " + str(row["observed_count"])
                    + " of " + str(row["analyzed_strokes"])
                    + " analyzed strokes" + frequency_meter
                    + "; supporting strokes: "
                    + (links if links else "No supporting strokes listed")
                    + more + ("; " + watch if watch else "") + "</li>"
                )

            findings = "".join(
                finding_item(row) for row in curated["findings"]
                if not fault_filter or row["fault_code"] == fault_filter
            )
            # Only display known candidates; this never implies coach approval.
            fault_options = "".join(
                '<option value="' + html.escape(code, quote=True) + '"'
                + (" selected" if code == fault_filter else "") + ">"
                + html.escape(FAULTS[code]["title"]) + "</option>"
                for code in sorted(FAULTS)
            )
            fault_controls = (
                f'<form method="get" action="/jobs/{job_id}/evidence">'
                '<label>Select a candidate fault <select name="fault">'
                + fault_options
                + '</select></label><button type="submit">'
                'Filter evidence</button></form>'
                + (f'<p>Showing candidate fault: <strong>'
                   f'{html.escape(fault_filter)}</strong> '
                   f'<a href="/jobs/{job_id}/evidence">Clear filter</a></p>'
                   if fault_filter else "")
            )
            stroke_list = (
                "<ul>" + strokes + "</ul>"
                if strokes or not fault_filter
                else "<p>No strokes flagged for this candidate fault.</p>"
            )
            body = ("<p><strong>Generated coaching withheld.</strong> "
                    "These measurements are unreviewed evidence, not "
                    "coach-approved advice or verified model accuracy.</p>"
                    + fault_controls
                    + "<h2>Seats</h2><ul>" + seats + "</ul>"
                    + "<h2>Stroke times</h2>" + stroke_list
                    + "<h2>Candidate findings</h2><ul>" + findings + "</ul>"
                    + f'<p><a href="/api/jobs/{job_id}/strokes.csv">'
                    'Export stroke evidence (CSV)</a></p>'
                    + f'<p><a href="/api/jobs/{job_id}/review.csv">'
                    'Blank coach-review worksheet</a></p>'
                    + f'<p><a href="/api/jobs/{job_id}/fault-review.csv">'
                    'Complete per-fault coach-review grid</a></p>'
                    + f'<p><a href="/jobs/{job_id}">Back to job</a></p>')
            self._send(200, _document("Saved evidence", body))

        def _reject_unsupported_method(self):
            # BaseHTTPRequestHandler defaults to 501 HTML without the local
            # Host/Origin gates or our defensive headers. Never use it for
            # common unsupported methods, including TRACE or OPTIONS.
            if not self._trusted_request():
                self._error(403)
                return
            allowed = _allowed_methods(urlsplit(self.path).path)
            if allowed is None:
                self._error(404)
                return
            self._error(405, allow=allowed)

        do_HEAD = _reject_unsupported_method
        do_PUT = _reject_unsupported_method
        do_PATCH = _reject_unsupported_method
        do_DELETE = _reject_unsupported_method
        do_OPTIONS = _reject_unsupported_method
        do_TRACE = _reject_unsupported_method
        do_CONNECT = _reject_unsupported_method

        def __getattr__(self, name):
            # Python's handler otherwise emits unsanitized 501 HTML for
            # extension verbs (e.g. PROPFIND), bypassing Host/Origin checks.
            if name.startswith("do_") and len(name) > 3:
                return self._reject_unsupported_method
            raise AttributeError(name)

        def do_GET(self):
            if not self._trusted_request():
                self._error(403)
                return
            route = urlsplit(self.path).path
            if route in ("/", "/history.csv"):
                try:
                    camera, status, clip = _history_filters(
                        urlsplit(self.path).query
                    )
                except ValueError:
                    self._error(400)
                    return
                if route == "/":
                    self._home(camera_filter=camera, status_filter=status,
                               clip_filter=clip)
                else:
                    self._history_csv(camera_filter=camera,
                                      status_filter=status, clip_filter=clip)
            elif route in ("/compare", "/compare.csv"):
                self._compare(urlsplit(self.path).query,
                              as_csv=(route == "/compare.csv"))
            elif route == "/api/jobs":
                try:
                    recent = permitted_recent_jobs()
                except Exception:
                    self._error(503)
                    return
                self._send(200, json.dumps(recent, sort_keys=True).encode("utf-8"),
                           mime="application/json; charset=utf-8")
            elif route.startswith("/api/jobs/") and route.endswith("/strokes.csv"):
                self._evidence(route[len("/api/jobs/"):-len("/strokes.csv")],
                               as_csv=True)
            elif route.startswith("/api/jobs/") and route.endswith("/review.csv"):
                self._evidence(route[len("/api/jobs/"):-len("/review.csv")],
                               review_template=True)
            elif route.startswith("/api/jobs/") and route.endswith("/fault-review.csv"):
                self._evidence(
                    route[len("/api/jobs/"):-len("/fault-review.csv")],
                    fault_template=True,
                )
            elif route.startswith("/api/jobs/") and route.endswith("/evidence"):
                self._evidence(route[len("/api/jobs/"):-len("/evidence")], api=True)
            elif route.startswith("/jobs/") and route.endswith("/evidence"):
                try:
                    fault = _fault_query(urlsplit(self.path).query)
                except ValueError:
                    self._error(400)
                    return
                self._evidence(route[len("/jobs/"):-len("/evidence")],
                               fault_filter=fault)
            elif route.startswith("/api/jobs/"):
                self._status(route[len("/api/jobs/"):], api=True)
            elif route.startswith("/jobs/"):
                try:
                    at = _seek_query(urlsplit(self.path).query)
                except ValueError:
                    self._error(400)
                    return
                self._status(route[len("/jobs/"):], at=at)
            elif route.startswith("/reports/"):
                self._report(route[len("/reports/"):])
            elif route.startswith("/media/"):
                self._media(route[len("/media/"):])
            else:
                allowed = _allowed_methods(route)
                self._error(405, allow=allowed) if allowed == "POST" else self._error(404)

        def _upload(self):
            content_type = self.headers.get("Content-Type", "")
            if (len(content_type) > 200 or not content_type.lower().startswith(
                    "multipart/form-data;") or
                    any(ord(char) < 32 or ord(char) > 126 for char in content_type)):
                self._error(415)
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._error(411)
                return
            if length > _MAX_UPLOAD:
                self._error(413)
                return
            if length < 1:
                self._error(400)
                return
            try:
                self.connection.settimeout(15)
                content = self.rfile.read(length)
                if len(content) != length:
                    raise ValueError("incomplete upload")
                raw = (b"Content-Type: " + content_type.encode("ascii")
                       + b"\r\nMIME-Version: 1.0\r\n\r\n" + content)
                message = BytesParser(policy=policy.default).parsebytes(raw)
                if not message.is_multipart():
                    self._error(400)
                    return
                parts = list(message.iter_parts())
                fields = {}
                for part in parts:
                    if part.is_multipart() or part.get_content_disposition() != "form-data":
                        raise ValueError("invalid upload field")
                    key = part.get_param("name", header="content-disposition")
                    if not key or key in fields:
                        raise ValueError("duplicate upload field")
                    fields[key] = part
                required = {"csrf", "permission", "provenance", "video"}
                allowed = required | {"analyze", "camera"}
                if not required.issubset(fields) or not set(fields).issubset(allowed):
                    raise ValueError("incorrect upload fields")
                def field(name):
                    data = fields[name].get_payload(decode=True)
                    if data is None or len(data) > 1024:
                        raise ValueError("invalid text field")
                    return data.decode("utf-8")
                if not hmac.compare_digest(field("csrf"), token):
                    self._error(403)
                    return
                analyze_now = False
                if "analyze" in fields:
                    if field("analyze") != "now":
                        self._error(400)
                        return
                    analyze_now = True
                permission = field("permission")
                provenance = field("provenance").strip()
                if permission != "granted" or not provenance or len(provenance) > 256:
                    self._error(422)
                    return
                camera = field("camera") if "camera" in fields else ""
                if camera not in _CAMERA_CHOICES:
                    self._error(422)
                    return
                filename = fields["video"].get_filename()
                if not filename or not isinstance(filename, str):
                    self._error(400)
                    return
                extension = Path(filename).suffix.lower()
                if extension not in _VIDEO_EXTENSIONS:
                    self._error(415)
                    return
                video = fields["video"].get_payload(decode=True)
                if not isinstance(video, bytes) or not video:
                    self._error(422)
                    return
                if len(video) > _MAX_VIDEO_BYTES:
                    self._error(413)
                    return
                if not plausible_container(video, extension):
                    self._error(415)
                    return
            except (UnicodeError, ValueError, TypeError, OSError):
                self._error(400)
                return

            try:
                private_uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination = private_uploads / (secrets.token_hex(16) + extension)
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(video)
                        stream.flush()
                        os.fsync(stream.fileno())
                    clip, created = register_clip(
                        destination, registry_path, permission="granted",
                        provenance=provenance, camera=camera or None,
                    )
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
                if not created:
                    destination.unlink(missing_ok=True)
            except RegistryError:
                self._error(422)
                return
            except Exception:
                self._error(503)
                return
            if analyze_now:
                try:
                    job = jobs.submit(clip["clip_id"])
                except JobError:
                    # The imported clip remains listed for a manual retry.
                    # Do not misreport an unavailable queue as success.
                    self._error(503)
                    return
                except Exception:
                    self._error(503)
                    return
                self._send(303, b"", location="/jobs/" + job["job_id"])
                return
            self._send(303, b"", location="/")

        def do_POST(self):
            if not self._trusted_request():
                self._error(403)
                return
            route = urlsplit(self.path).path
            if route not in ("/jobs", "/revoke", "/upload"):
                allowed = _allowed_methods(route)
                self._error(405, allow=allowed) if allowed == "GET" else self._error(404)
                return
            # Reject ambiguous framing before reading or mutating private data.
            # The local server does not implement chunked request decoding.
            lengths = self.headers.get_all("Content-Length") or []
            if (len(lengths) != 1
                    or re.fullmatch(r"[0-9]+", lengths[0]) is None
                    or self.headers.get_all("Transfer-Encoding")):
                self._error(400)
                return
            if route == "/upload":
                self._upload()
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/x-www-form-urlencoded":
                self._error(415)
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._error(411)
                return
            if length > _MAX_FORM:
                self._error(413)
                return
            if length < 1:
                self._error(400)
                return
            try:
                # Never parse or act on a partial form, even if it looks valid.
                # Bound a stalled local connection rather than leaving a worker thread.
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._error(400)
                    return
                body = raw.decode("utf-8")
                params = parse_qs(body, keep_blank_values=True, strict_parsing=True,
                                  max_num_fields=3)
                if set(params) != {"csrf", "clip_id"} or any(
                    len(v) != 1 for v in params.values()
                ):
                    self._error(400)
                    return
                csrf, clip_id = params["csrf"][0], params["clip_id"][0]
                if not hmac.compare_digest(csrf, token):
                    self._error(403)
                    return
                if not re.fullmatch(r"[0-9a-f]{64}", clip_id):
                    self._error(400)
                    return
                if route == "/revoke":
                    revoke_clip(clip_id, registry_path)
                    destination = "/"
                else:
                    record = jobs.submit(clip_id)
                    destination = "/jobs/" + record["job_id"]
            except TimeoutError:
                self._error(400)
                return
            except (UnicodeError, ValueError, JobError):
                self._error(422)
                return
            except Exception:
                self._error(503)
                return
            self._send(303, b"", location=destination)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    httpd = Server((host, port), Handler)
    httpd.csrf_token = token
    return httpd


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private loopback StrokeSense Alpha")
    parser.add_argument("--registry-db", default=str(DEFAULT_DB))
    private_root = Path(__file__).resolve().parents[1] / "results"
    parser.add_argument("--jobs-db", default=str(private_root / "analysis_jobs.sqlite3"))
    parser.add_argument("--results", default=str(private_root / "jobs"))
    parser.add_argument("--uploads", default=str(private_root / "uploads"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    with JobQueue(registry_db=args.registry_db, job_db=args.jobs_db,
                  results_root=args.results) as jobs:
        with create_server(jobs, registry_db=args.registry_db,
                           upload_dir=args.uploads, port=args.port) as server:
            print(f"Local StrokeSense: http://127.0.0.1:{server.server_address[1]}/")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
