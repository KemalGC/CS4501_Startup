"""Local-only, dependency-free browser UI for registered StrokeSense jobs.

This is deliberately not a public web service. Every request is Host/Origin
restricted; queue writes require a per-process anti-CSRF token. Report retrieval
is revalidated against the job's trusted results root.
"""
from __future__ import annotations

import argparse
import hashlib
from email import policy
from email.parser import BytesParser
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from .evidence import verify_evidence_snapshot
from .jobs import JobError, JobQueue
from .media import plausible_container
from .evidence import validate_public_evidence_snapshot
from .registry import (DEFAULT_DB, RegistryError, analysis_permission_granted,
                       list_clips, register_clip, revoke_clip)


_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_FORM = 2048
_MAX_UPLOAD = 25 * 1024 * 1024
_VIDEO_EXTENSIONS = frozenset({'.mp4', '.mov', '.mkv', '.avi', '.webm'})
_MAX_REPORT = 32 * 1024 * 1024
_MAX_METRICS = 16 * 1024 * 1024
_PAGE_CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
             "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
_REPORT_CSP = ("sandbox; default-src 'none'; img-src data:; "
               "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")


def _document(title: str, content: str, *, refresh: bool = False) -> bytes:
    safe_title = html.escape(title, quote=True)
    meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'{meta}<title>{safe_title}</title>'
            '<style>body{font:16px/1.5 system-ui,sans-serif;max-width:820px;'
            'margin:2rem auto;padding:0 1rem;color:#202734;background:#f7f9fc}'
            'main{background:white;border:1px solid #dbe1e9;border-radius:12px;'
            'padding:1.4rem}button{padding:.45rem 1rem;cursor:pointer}'
            'code{overflow-wrap:anywhere}label{display:block;margin:1rem 0}'
            'a{color:#164d9a}</style></head><body><main>'
            f'<h1>{safe_title}</h1>{content}</main></body></html>').encode("utf-8")


def _allowed_methods(route: str) -> str | None:
    """HTTP Allow for known local endpoints; unknown routes stay 404."""
    if (route in ("/", "/api/jobs") or route.startswith("/api/jobs/")
            or route.startswith("/jobs/") or route.startswith("/reports/")):
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

    class Handler(BaseHTTPRequestHandler):
        server_version = "StrokeSense"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Do not emit clip IDs, private paths or raw user-supplied routes.
            pass

        def _send(self, code, data: bytes, *, mime="text/html; charset=utf-8",
                  csp=_PAGE_CSP, location=None, allow=None):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            if location is not None:
                self.send_header("Location", location)
            if allow is not None:
                self.send_header("Allow", allow)
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

        def _home(self):
            try:
                clips = [c for c in list_clips(registry_path)
                         if c["permission"] == "granted"]
            except Exception:
                self._error(503)
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
            history_items = "".join(
                '<li><a href="/jobs/' + html.escape(row["job_id"], quote=True)
                + '">Analysis ' + html.escape(row["job_id"][:12])
                + '</a> — ' + html.escape(row["status"])
                + ' — coaching: withheld</li>'
                for row in recent if _JOB_ID.fullmatch(row["job_id"])
            )
            history = ("<h2>Recent analyses</h2><ol>" + history_items + "</ol>"
                       if history_items else "<h2>Recent analyses</h2><p>None yet.</p>")
            upload_form = (
                '<h2>Register a new local clip</h2>'
                '<form method="post" action="/upload" enctype="multipart/form-data">'
                '<label>Video (.mp4, .mov, .mkv, .avi, .webm): '
                '<input type="file" name="video" required></label>'
                '<label>Permission attestation: '
                '<input type="checkbox" name="permission" value="granted" required>'
                'I attest I have permission to analyze this recording</label>'
                '<label>Permission source / provenance: '
                '<input type="text" name="provenance" maxlength="256" required></label>'
                '<label><input type="checkbox" name="analyze" value="now" checked>'
                ' Analyze immediately after import</label>'
                '<input type="hidden" name="csrf" value="'
                + html.escape(token, quote=True)
                + '"><button type="submit">Import locally</button></form>'
            )
            body = ("<p>Local prototype. Permission is an operator assertion, "
                    "not independent consent verification. Analysis runs on "
                    "your computer. No generated LLM advice is released here.</p>"
                    + controls + upload_form + history)
            self._send(200, _document("StrokeSense local Alpha", body))

        def _status(self, job_id: str, *, api=False):
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
            content = (f"<p>Job: <code>{job_id}</code></p>"
                       f"<p>Status: <strong>{status}</strong></p>"
                       '<p>Coaching: <strong>withheld</strong></p>'
                       + message + link
                       + '<p><a href="/">Choose another clip</a></p>')
            self._send(200, _document("Analysis status", content,
                                      refresh=status in ("queued", "running")))

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


        def _evidence(self, job_id: str, *, api=False):
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
            strokes = "".join(
                "<li>Stroke " + html.escape(str(row.get("index", "?")))
                + " at " + html.escape(str(row.get("catch_seconds", "?")))
                + " seconds; faults: "
                + html.escape(", ".join(str(x) for x in row.get("fault_codes", [])))
                + "</li>" for row in curated["strokes"]
            )
            findings = "".join(
                "<li>" + html.escape(str(row.get("fault_code", "unknown")))
                + " — " + html.escape(str(row.get("status", "unknown")))
                + "</li>" for row in curated["findings"]
            )
            body = ("<p><strong>Generated coaching withheld.</strong> "
                    "These measurements are unreviewed evidence, not "
                    "coach-approved advice or verified model accuracy.</p>"
                    "<h2>Seats</h2><ul>" + seats + "</ul>"
                    "<h2>Stroke times</h2><ul>" + strokes + "</ul>"
                    "<h2>Candidate findings</h2><ul>" + findings + "</ul>"
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
            if route == "/":
                self._home()
            elif route == "/api/jobs":
                try:
                    recent = permitted_recent_jobs()
                except Exception:
                    self._error(503)
                    return
                self._send(200, json.dumps(recent, sort_keys=True).encode("utf-8"),
                           mime="application/json; charset=utf-8")
            elif route.startswith("/api/jobs/") and route.endswith("/evidence"):
                self._evidence(route[len("/api/jobs/"):-len("/evidence")], api=True)
            elif route.startswith("/jobs/") and route.endswith("/evidence"):
                self._evidence(route[len("/jobs/"):-len("/evidence")])
            elif route.startswith("/api/jobs/"):
                self._status(route[len("/api/jobs/"):], api=True)
            elif route.startswith("/jobs/"):
                self._status(route[len("/jobs/"):])
            elif route.startswith("/reports/"):
                self._report(route[len("/reports/"):])
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
                if set(fields) not in (required, required | {"analyze"}):
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
                        provenance=provenance,
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
