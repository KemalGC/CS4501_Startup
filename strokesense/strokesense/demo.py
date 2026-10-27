"""One-command *synthetic* offline browser workflow demonstration.

This is not a real-video accuracy, decoder, coaching or model demo.
Temporary, deliberately fake media/report/evidence exercise the local HTTP
contract without user recordings, model downloads, provider calls or secrets.
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading

from .evidence import build_evidence_snapshot
from .jobs import JobQueue
from .media import UndecodableMediaError
from .strokes import FAULTS
from .web import create_server

_SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12
_BOUNDARY = "StrokeSenseOfflineFixture"


def _multipart(csrf: str) -> tuple[bytes, str]:
    """Construct only our known synthetic payload, not arbitrary user data."""
    chunks = []
    for name, value in (
        ("csrf", csrf),
        ("permission", "granted"),
        ("provenance", "SYNTHETIC OFFLINE FIXTURE ONLY"),
        ("analyze", "now"),
    ):
        chunks.append((
            f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"'
            f'\r\n\r\n{value}\r\n'
        ).encode("ascii"))
    chunks.append((
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="video"; '
        'filename="synthetic.mp4"\r\nContent-Type: video/mp4\r\n\r\n'
    ).encode("ascii") + _SYNTHETIC_MP4 + b"\r\n")
    chunks.append(f"--{_BOUNDARY}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={_BOUNDARY}"


def _http(port: int, method: str, path: str, *, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def _snapshot() -> dict:
    # Deliberately fabricated, not measurements of an athlete.
    fault = next(iter(FAULTS))
    return build_evidence_snapshot(
        {"rowers": [{
            "seat": "synthetic-seat", "track": 1,
            "strokes": [
                {"idx": 0, "catch": 1, "finish": 5, "next_catch": 10,
                 "faults": [fault]},
                {"idx": 1, "catch": 11, "finish": 16, "next_catch": 21,
                 "faults": []},
                {"idx": 2, "catch": 22, "finish": 27, "next_catch": 32,
                 "faults": []},
            ],
        }]},
        analysis_key="synthetic-offline-browser-demo", fps=15.0,
    )


def run_demo(*, simulate_failure: bool = False) -> dict:
    """Exercise upload -> job -> report -> evidence over real loopback HTTP.

    Return an intentionally safe public summary; nothing persistent remains.
    A fake analyzer writes a labeled toy report, never running pose inference.
    """
    if type(simulate_failure) is not bool:
        raise ValueError("simulate_failure must be a boolean")

    def analyze(_video, *, out_dir):
        if simulate_failure:
            raise UndecodableMediaError("invalid_media")
        target = Path(out_dir) / "synthetic"
        target.mkdir(parents=True)
        report = target / "report.html"
        report.write_text(
            "<!doctype html><h1>SYNTHETIC OFFLINE fake report</h1>",
            encoding="utf-8",
        )
        (target / "metrics.json").write_text(
            json.dumps({"evidence": _snapshot()}), encoding="utf-8"
        )
        return {"report": report}

    with tempfile.TemporaryDirectory(prefix="strokesense_fixture_") as directory:
        root = Path(directory)
        registry = root / "registry.sqlite3"
        with JobQueue(
            registry_db=registry, job_db=root / "jobs.sqlite3",
            results_root=root / "results", analyze_fn=analyze,
        ) as jobs:
            with create_server(
                jobs, registry_db=registry, upload_dir=root / "uploads", port=0,
            ) as server:
                thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.01}, daemon=True,
                )
                thread.start()
                try:
                    port = server.server_address[1]
                    payload, mime = _multipart(server.csrf_token)
                    code, headers, _ = _http(
                        port, "POST", "/upload", body=payload,
                        headers={"Content-Type": mime},
                    )
                    redirect = headers.get("Location", "")
                    if code != 303 or not re.fullmatch(
                        r"/jobs/[a-f0-9]{32}", redirect
                    ):
                        raise RuntimeError("synthetic upload/queue did not complete")
                    job_id = redirect.rsplit("/", 1)[-1]
                    final = jobs.wait(job_id, timeout=5)
                    code, _, status_bytes = _http(
                        port, "GET", "/api/jobs/" + job_id
                    )
                    if code != 200:
                        raise RuntimeError("synthetic job status unavailable")
                    status = json.loads(status_bytes)
                    if status.get("status") != final["status"]:
                        raise RuntimeError("synthetic job status inconsistent")

                    report_code, _, report_body = _http(
                        port, "GET", "/reports/" + job_id
                    )
                    evidence_code, _, evidence_bytes = _http(
                        port, "GET", "/api/jobs/" + job_id + "/evidence"
                    )
                    if simulate_failure:
                        if (final["status"] != "failed"
                                or status.get("error_code") != "invalid_media"
                                or report_code != 404 or evidence_code != 404):
                            raise RuntimeError("synthetic failure did not withhold")
                        report_seen, strokes = False, 0
                    else:
                        if (final["status"] != "succeeded" or report_code != 200
                                or b"SYNTHETIC OFFLINE" not in report_body
                                or evidence_code != 200):
                            raise RuntimeError("synthetic report/evidence missing")
                        evidence = json.loads(evidence_bytes)
                        if evidence.get("coaching_state") != "withheld":
                            raise RuntimeError("synthetic coaching not withheld")
                        strokes = len(evidence["evidence"]["strokes"])
                        if strokes != 3:
                            raise RuntimeError("synthetic stroke evidence incomplete")
                        report_seen = True
                    return {
                        "mode": "synthetic-offline",
                        "status": final["status"],
                        "error_code": status.get("error_code"),
                        "coaching_state": "withheld",
                        "synthetic_report_observed": report_seen,
                        "evidence_strokes": strokes,
                        "real_video_used": False,
                        "pose_inference_used": False,
                        "live_llm_used": False,
                    }
                finally:
                    server.shutdown()
                    thread.join(timeout=3)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline synthetic StrokeSense browser workflow smoke demo"
    )
    parser.add_argument(
        "--simulate-failure", action="store_true",
        help="exercise a failed synthetic analysis with withheld results",
    )
    args = parser.parse_args(argv)
    try:
        result = run_demo(simulate_failure=args.simulate_failure)
    except Exception:
        # No temporary private paths, tracebacks or credentials in CLI output.
        print(json.dumps({
            "mode": "synthetic-offline", "status": "failed",
            "error_code": "demo_failed", "coaching_state": "withheld",
            "real_video_used": False, "pose_inference_used": False,
            "live_llm_used": False,
        }, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
