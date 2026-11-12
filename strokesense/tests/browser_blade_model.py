"""Native controls/submission test. Synthetic media and fake analysis, no accuracy."""
from pathlib import Path
import json
import os
import shutil
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_blade_web import BladeWebTests


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('google-chrome') or shutil.which('chromium')
    if not executable: raise RuntimeError('Chrome or Chromium is required')
    case = BladeWebTests(); case.setUp()
    try:
        with patch.dict(os.environ, {'STROKESENSE_BLADE_MODEL': 'test-local:1'}), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=executable, headless=True)
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                assert page.goto(case.origin+'/blade?clip='+case.cid).status == 200
                page.wait_for_function("document.querySelector('#blade-canvas').width === 128")
                assert case.jobs.list_recent() == []
                for width in (320, 390, 1280):
                    page.set_viewport_size({'width': width, 'height': 900})
                    bounds = page.locator('#blade-canvas').bounding_box()
                    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1
                canvas = page.locator('#blade-canvas'); canvas.focus(); page.keyboard.press('ArrowLeft')
                assert page.locator('[name=x]').input_value() != ''
                page.locator('[name=confirm]').check()
                page.keyboard.press('Tab')
                page.locator('[name=x]').fill('0.3'); page.locator('[name=y]').fill('0.6')
                assert not page.locator('[name=confirm]').is_checked()
                page.locator('[name=confirm]').check()
                with page.expect_response(lambda r: r.url == case.origin+'/blade' and r.request.method == 'POST') as posted:
                    page.get_by_role('button', name='Analyze blade entries', exact=True).click()
                assert posted.value.status == 303
                page.wait_for_url(case.origin+'/jobs/*')
                job = case.jobs.wait(page.url.rsplit('/', 1)[-1], timeout=5)
                assert job['status'] == 'succeeded'
                assert len(case.seen) == 1 and case.seen[0]['version'] == 3
                assert case.seen[0]['point'] == [.3, .6]
                print(json.dumps({'browser': browser.version, 'viewports': [320, 390, 1280],
                    'confirmed_one_blade': True, 'fake_analyzer': True, 'no_live_accuracy_claim': True}))
            finally: browser.close()
    finally: case.doCleanups()
    return 0


if __name__ == '__main__': raise SystemExit(main())
