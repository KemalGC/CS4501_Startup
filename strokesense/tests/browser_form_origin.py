"""Optional native-browser regression; synthetic video header, no inference.

Run: python strokesense/tests/browser_form_origin.py
Requires the test-only playwright==1.58.0 package and an installed Chrome or
Chromium. Does not download browsers, access providers, or use private footage.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips
from strokesense.web import create_server


def main():
    from playwright.sync_api import sync_playwright

    executable = (shutil.which("google-chrome") or shutil.which("chromium")
                  or shutil.which("chromium-browser"))
    if executable is None:
        raise RuntimeError("Install Chrome/Chromium before this optional browser test")
    with tempfile.TemporaryDirectory(prefix="strokesense-browser-") as tmp:
        root = Path(tmp)
        registry = root / "registry.sqlite3"
        source = root / "synthetic.mp4"
        video = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12
        source.write_bytes(video)
        with JobQueue(registry_db=registry, job_db=root / "jobs.sqlite3",
                      results_root=root / "results",
                      analyze_fn=lambda *a, **k: None) as jobs:
            with create_server(jobs, registry_db=registry, port=0) as server:
                thread = threading.Thread(target=server.serve_forever,
                                          kwargs={"poll_interval": 0.01}, daemon=True)
                thread.start()
                origin = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(
                            executable_path=executable, headless=True)
                        try:
                            page = browser.new_page(java_script_enabled=False)
                            home = page.goto(origin + "/")
                            assert home.status == 200
                            form = page.locator('form[action="/upload"]')
                            form.locator('input[name="video"]').set_input_files(str(source))
                            form.locator('input[name="permission"]').check()
                            form.locator('input[name="provenance"]').fill("synthetic browser fixture")
                            form.locator('input[name="analyze"]').uncheck()
                            with page.expect_response(
                                lambda response: response.url == origin + "/upload"
                                and response.request.method == "POST"
                            ) as posted:
                                form.locator('button[type="submit"]').click()
                            response = posted.value
                            actual_origin = response.request.all_headers().get("origin")
                            rows = list_clips(registry, show_paths=True)
                            # Print only fixed diagnostic fields: never tokens or private paths.
                            print(json.dumps({
                                "browser": browser.version,
                                "policy": home.headers.get("referrer-policy"),
                                "upload_status": response.status,
                                "origin_is_null": actual_origin == "null",
                                "origin_matches": actual_origin == origin,
                                "registered_clips": len(rows),
                            }), flush=True)
                            assert response.status == 303, (
                                f"native form upload returned HTTP {response.status}, expected 303")
                            assert actual_origin == origin, "browser lost same-origin request identity"
                            page.wait_for_url(origin + "/")
                            assert len(rows) == 1
                            assert Path(rows[0]["source_path"]).read_bytes() == video
                            assert jobs.list_recent(limit=20) == []
                        finally:
                            browser.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
