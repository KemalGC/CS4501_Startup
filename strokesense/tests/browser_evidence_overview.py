"""Optional real-Chrome evidence overview geometry smoke test (#91).

Only uses synthetic snapshot fixtures and local-loopback HTTP. No genuine
rowing footage, pose model, LLM, remote requests, or coach labels.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_ui import EvidenceInterfaceTests


def main():
    from playwright.sync_api import sync_playwright

    executable = (shutil.which("google-chrome") or shutil.which("chromium")
                  or shutil.which("chromium-browser"))
    if executable is None:
        raise RuntimeError("An installed Chrome/Chromium is required for browser smoke test")

    rig = EvidenceInterfaceTests(
        methodName="test_human_readable_evidence_links_to_strokes_and_times"
    )
    rig.setUp()
    try:
        job_id = rig.succeed()
        origin = f"http://127.0.0.1:{rig.port}"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, headless=True)
            try:
                page = browser.new_page(java_script_enabled=False)
                widths = []
                for width in (320, 390, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    response = page.goto(f"{origin}/jobs/{job_id}/evidence")
                    assert response.status == 200, f"evidence route {response.status}"
                    assert page.locator(".evidence-stats .evidence-stat").count() == 3
                    assert page.locator(".evidence-stat dd").all_text_contents() == [
                        "1", "3", "1"
                    ], "overview totals differ from saved synthetic snapshot"
                    for selector in (
                        ".evidence-workspace", ".evidence-stats",
                        ".evidence-jump", "#evidence-seats",
                        "#evidence-strokes", "#evidence-findings",
                        ".evidence-downloads",
                    ):
                        bounds = page.locator(selector).bounding_box()
                        assert bounds is not None, f"{selector} missing at {width}px"
                        assert bounds["x"] >= -1, f"{selector} clipped left at {width}px"
                        assert bounds["x"] + bounds["width"] <= width + 1, (
                            f"{selector} clipped right at {width}px"
                        )
                    widths.append(width)
                page.locator('nav.evidence-jump a[href="#evidence-findings"]').click()
                assert page.url.endswith("#evidence-findings")
                assert page.locator("#evidence-findings h2").inner_text() == (
                    "Candidate findings"
                )
                print(json.dumps({
                    "browser": browser.version,
                    "synthetic_snapshot_only": True,
                    "evidence_status": 200,
                    "card_count": 3,
                    "rendered_viewports": widths,
                    "anchor_navigation": "passed",
                }), flush=True)
            finally:
                browser.close()
    finally:
        rig.doCleanups()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
