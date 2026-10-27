"""Local-only, dependency-free browser UI for registered StrokeSense jobs.

This is deliberately not a public web service. Every request is Host/Origin
restricted; queue writes require a per-process anti-CSRF token. Report retrieval
is revalidated against the job's trusted results root.
"""
from __future__ import annotations

import argparse
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from .jobs import JobError, JobQueue
from .registry import DEFAULT_DB, list_clips


_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_FORM = 2048
_MAX_REPORT = 32 * 1024 * 1024
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


def create_server(
    jobs: JobQueue, *, registry_db, host: str = "127.0.0.1", port: int = 0,
) -> ThreadingHTTPServer:
    """Return an explicit loopback-only server; caller owns its lifecycle."""
    if host != "127.0.0.1":
        raise ValueError("local UI can bind only to 127.0.0.1")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid HTTP port")
    token = secrets.token_urlsafe(32)
    registry_path = Path(registry_db).expanduser().resolve()
    result_root = jobs._results_root.resolve()  # Trusted local JobQueue directory.

    class Handler(BaseHTTPRequestHandler):
        server_version = "StrokeSense"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Do not emit clip IDs, private paths or raw user-supplied routes.
            pass

        def _send(self, code, data: bytes, *, mime="text/html; charset=utf-8",
                  csp=_PAGE_CSP, location=None):
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
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _error(self, status):
            self._send(status, _document("Request unavailable",
                                         "<p>The requested action is unavailable.</p>"))

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
                )
            else:
                controls = ("<p>No permission-claimed clips are registered. "
                            "Import a clip with the local registry CLI first.</p>")
            try:
                recent = jobs.list_recent(limit=20)
            except Exception:
                self._error(503)
                return
            history_items = "".join(
                '<li><a href="/jobs/' + html.escape(row["job_id"], quote=True)
                + '">Analysis ' + html.escape(row["job_id"][:12])
                + '</a> — ' + html.escape(row["status"]) + '</li>'
                for row in recent if _JOB_ID.fullmatch(row["job_id"])
            )
            history = ("<h2>Recent analyses</h2><ol>" + history_items + "</ol>"
                       if history_items else "<h2>Recent analyses</h2><p>None yet.</p>")
            body = ("<p>Local prototype. Permission is an operator assertion, "
                    "not independent consent verification. Analysis runs on "
                    "your computer. No generated LLM advice is released here.</p>"
                    + controls + history)
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
            if api:
                body = json.dumps(record, sort_keys=True).encode("utf-8")
                self._send(200, body, mime="application/json; charset=utf-8")
                return
            status = html.escape(record["status"])
            err = record.get("error_code")
            message = f'<p>Error: <code>{html.escape(err)}</code></p>' if err else ""
            link = (f'<p><a href="/reports/{job_id}">Open technique report</a></p>'
                    if status == "succeeded" else "")
            content = (f"<p>Job: <code>{job_id}</code></p>"
                       f"<p>Status: <strong>{status}</strong></p>"
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
                if not record or record["status"] != "succeeded":
                    self._error(404)
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
                data = target.read_bytes()
            except (OSError, ValueError, TypeError):
                self._error(404)
                return
            except Exception:
                self._error(503)
                return
            self._send(200, data, csp=_REPORT_CSP)

        def do_GET(self):
            if not self._trusted_request():
                self._error(403)
                return
            route = urlsplit(self.path).path
            if route == "/":
                self._home()
            elif route == "/api/jobs":
                try:
                    recent = jobs.list_recent(limit=20)
                except Exception:
                    self._error(503)
                    return
                self._send(200, json.dumps(recent, sort_keys=True).encode("utf-8"),
                           mime="application/json; charset=utf-8")
            elif route.startswith("/api/jobs/"):
                self._status(route[len("/api/jobs/"):], api=True)
            elif route.startswith("/jobs/"):
                self._status(route[len("/jobs/"):])
            elif route.startswith("/reports/"):
                self._report(route[len("/reports/"):])
            else:
                self._error(404)

        def do_POST(self):
            if not self._trusted_request():
                self._error(403)
                return
            if urlsplit(self.path).path != "/jobs":
                self._error(404)
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
                body = self.rfile.read(length).decode("utf-8")
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
                record = jobs.submit(clip_id)
            except (UnicodeError, ValueError, JobError):
                self._error(422)
                return
            except Exception:
                self._error(503)
                return
            self._send(303, b"", location="/jobs/" + record["job_id"])

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
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    with JobQueue(registry_db=args.registry_db, job_db=args.jobs_db,
                  results_root=args.results) as jobs:
        with create_server(jobs, registry_db=args.registry_db,
                           port=args.port) as server:
            print(f"Local StrokeSense: http://127.0.0.1:{server.server_address[1]}/")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
