"""Native Chrome smoke test for local analysis review UI (#93).

Synthetic job states only. Does not decode video or establish coach accuracy.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_job_status_steps as _fixture


def main():
    from playwright.sync_api import sync_playwright

    executable = (shutil.which("google-chrome") or shutil.which("chromium")
                  or shutil.which("chromium-browser"))
    if not executable:
        raise RuntimeError("An installed Chrome/Chromium executable is required")
    rig = _fixture.JobStatusStagesTests(
        methodName="test_queued_running_and_success_stages_are_truthful"
    )
    rig.setUp()
    try:
        origin = f"http://127.0.0.1:{rig.server.server_address[1]}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable, headless=True
            )
            try:
                page = browser.new_page(java_script_enabled=False)
                widths = []
                for width in (320, 390, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    record = {
                        "job_id": rig.job_id, "clip_id": rig.clip_id,
                        "status": "succeeded", "coaching_state": "withheld",
                        "error_code": None,
                    }
                    with patch.object(rig.jobs, "get", return_value=record), patch.object(
                            rig.jobs, "media_artifact", return_value=None):
                        response = page.goto(origin + "/jobs/" + rig.job_id)
                    assert response is not None and response.status == 200
                    assert page.locator(".result-action").count() == 2
                    assert page.get_by_role(
                        "link", name="Open technique report"
                    ).is_visible()
                    assert page.get_by_role(
                        "link", name="Inspect saved evidence"
                    ).is_visible()
                    for selector in (".result-workspace", ".result-actions",
                                     ".result-action", ".result-review-notice"):
                        for node in page.locator(selector).all():
                            box = node.bounding_box()
                            assert box is not None, f"missing {selector}"
                            assert box["x"] >= -1, f"{selector} overflows left at {width}"
                            assert box["x"] + box["width"] <= width + 1, (
                                f"{selector} overflows right at {width}: {box}"
                            )
                    cards = [n.bounding_box() for n in page.locator(".result-action").all()]
                    if width <= 390:
                        assert cards[1]["y"] >= cards[0]["y"] + cards[0]["height"] - 1
                    else:
                        assert cards[1]["x"] >= cards[0]["x"] + cards[0]["width"] - 1
                    widths.append(width)

                for state, error, selector in (
                    ("queued", None, ".status-processing"),
                    ("running", None, ".status-processing"),
                    ("failed", "analysis_failed", ".status-error"),
                ):
                    record = {
                        "job_id": rig.job_id, "clip_id": rig.clip_id,
                        "status": state, "coaching_state": "withheld",
                        "error_code": error,
                    }
                    with patch.object(rig.jobs, "get", return_value=record):
                        response = page.goto(origin + "/jobs/" + rig.job_id)
                    assert response is not None and response.status == 200
                    assert page.locator(selector).is_visible()
                    assert page.locator(".result-workspace").count() == 0
                    if state == "failed":
                        assert page.get_by_role(
                            "button", name="Retry analysis"
                        ).is_visible()
                print(json.dumps({
                    "browser": browser.version,
                    "synthetic_job_states_only": True,
                    "responsive_viewports": widths,
                    "completed_cards": 2,
                    "queued_running_failed": "passed",
                }), flush=True)
            finally:
                browser.close()
    finally:
        rig.doCleanups()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
