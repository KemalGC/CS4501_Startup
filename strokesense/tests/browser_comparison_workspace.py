"""Read-only native Chrome comparison UI smoke test (#92).

Two local synthetic evidence snapshots; no genuine footage, live inference,
external service, user identifiers, or coach-reviewed technique labels.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_ui import EvidenceInterfaceTests


def main():
    from playwright.sync_api import sync_playwright

    executable = (shutil.which("google-chrome") or shutil.which("chromium")
                  or shutil.which("chromium-browser"))
    if not executable:
        raise RuntimeError("Chrome/Chromium must already be installed")
    rig = EvidenceInterfaceTests(
        methodName="test_human_readable_evidence_links_to_strokes_and_times"
    )
    rig.setUp()
    try:
        before, after = rig.succeed(), rig.succeed()
        origin = f"http://127.0.0.1:{rig.port}"
        comparison_url = origin + "/compare?" + urlencode({
            "before": before, "after": after
        })
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable, headless=True
            )
            try:
                page = browser.new_page(java_script_enabled=False)
                checked = []
                for width in (320, 390, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    response = page.goto(comparison_url)
                    assert response.status == 200, (
                        f"comparison route returned {response.status}"
                    )
                    cards = page.locator(".comparison-run")
                    assert cards.count() == 2, "expected two saved run cards"
                    assert page.locator(".comparison-table tbody a").count() == 2
                    for selector in (
                        ".comparison-panel", ".comparison-runs",
                        ".comparison-run", ".comparison-findings",
                        ".comparison-scroll", ".comparison-utilities",
                    ):
                        for node in page.locator(selector).all():
                            box = node.bounding_box()
                            assert box is not None, f"missing {selector}"
                            assert box["x"] >= -1, (
                                f"{selector} clipped left at {width}px: {box}"
                            )
                            assert box["x"] + box["width"] <= width + 1, (
                                f"{selector} clipped right at {width}px: {box}"
                            )
                    if width < 720:
                        scroll = page.locator(".comparison-scroll").evaluate(
                            "(element) => element.scrollWidth > element.clientWidth"
                        )
                        assert scroll, "small viewport should scroll fault table internally"
                    checked.append(width)
                page.locator(
                    f'.comparison-table a[href="/jobs/{before}/evidence?fault=early_arms"]'
                ).click()
                assert page.url.endswith(
                    f"/jobs/{before}/evidence?fault=early_arms"
                ), "fault drill-down did not navigate"
                assert page.locator("#evidence-findings").is_visible()
                print(json.dumps({
                    "browser": browser.version,
                    "synthetic_snapshot_only": True,
                    "responsive_viewports": checked,
                    "mobile_internal_table_scroll": True,
                    "fault_link_navigation": "passed",
                }), flush=True)
            finally:
                browser.close()
    finally:
        rig.doCleanups()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
