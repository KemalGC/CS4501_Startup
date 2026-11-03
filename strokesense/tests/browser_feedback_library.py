"""Native library -> report -> saved review journey; synthetic fixtures only."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_feedback_library import ReportLibraryTests


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('chromium') or shutil.which('google-chrome')
    if not executable: raise RuntimeError('Chrome/Chromium required')
    case = ReportLibraryTests(); case.setUp()
    try:
        if shutil.which('ffmpeg'):
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                '-i', 'color=c=teal:s=320x180:r=24', '-t', '2', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', str(case.root/'source.mp4')], check=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=executable, headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                assert page.goto(case.origin+'/library').status == 200
                assert page.locator('#welcome').is_visible()
                assert page.locator('#reports-library').is_hidden()
                page.get_by_label('I agree to provide feedback', exact=False).check()
                page.get_by_role('button', name='Begin review', exact=False).click()
                page.wait_for_selector('#reports-library:not([hidden])')
                assert page.locator('#workspace').is_hidden()
                assert page.locator('.report-card').count() == 4
                assert '1 reports' in page.locator('#reports-count').inner_text()
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
                missing = page.locator('[data-clip="clip-three"]')
                assert missing.get_by_text('Report unavailable', exact=True).count() == 1
                assert missing.get_by_role('link', name='Open report', exact=True).count() == 0
                page.get_by_label('Find a recording', exact=True).fill('Second')
                assert page.locator('.report-card').count() == 1
                page.get_by_role('link', name='Open diagnostic', exact=True).click()
                page.wait_for_selector('#report-panel:not([hidden])')
                assert 'Second.mp4' in page.locator('#clip-title').inner_text()
                assert page.locator('#report-frame').get_attribute('src') == '/asset/clip-two/report'
                assert page.locator('#report-frame').get_attribute('sandbox') == ''
                assert page.frame_locator('#report-frame').get_by_role('heading', name='Detection diagnostic only').inner_text() == 'Detection diagnostic only'
                page.reload(); page.wait_for_selector('#report-panel:not([hidden])')
                assert page.locator('#report-frame').get_attribute('src') == '/asset/clip-two/report'
                assert case.server.store.rows() == []
                # Normal review remains saveable after opening a saved report.
                page.get_by_label('usefulness 4 — Very useful', exact=True).check()
                page.locator('[name=accuracy][value=not_applicable]').check()
                with page.expect_response(lambda r: r.url.endswith('/api/reviews') and r.request.method == 'POST') as save:
                    page.get_by_role('button', name='Save & next aspect', exact=False).click()
                assert save.value.status == 200
                page.wait_for_function("document.querySelector('#progress').textContent === '1 / 6 saved'")
                page.locator('#reports-nav').click(); page.wait_for_selector('#reports-library:not([hidden])')
                page.locator('[data-clip="clip-two"]').get_by_role('link', name='Review video').click()
                page.wait_for_function("document.querySelector('#progress').textContent === '1 / 6 saved'")
                assert len(case.server.store.rows()) == 1
                page.on('dialog', lambda d: d.accept())
                page.get_by_role('button', name='Finish session', exact=True).click()
                page.wait_for_selector('#welcome:not([hidden])')
                assert page.locator('#reports-library').is_hidden()
                assert (page.request.get(case.origin+'/asset/clip-two/report')).status == 401
                assert not errors, errors
                print(json.dumps({'browser': browser.version, 'report_linking': 'passed',
                    'viewports': [320,390,768,1440], 'deep_link_reload': 'passed',
                    'consent_and_asset_gating': 'passed', 'synthetic_feedback_only': True}))
            finally: browser.close()
    finally: case.doCleanups()


if __name__ == '__main__': main()
