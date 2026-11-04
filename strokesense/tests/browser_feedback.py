"""Native-browser feedback journey; synthetic data never enters a real study DB."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_feedback import FeedbackTests


def main():
    from playwright.sync_api import sync_playwright, expect
    exe=shutil.which('chromium') or shutil.which('google-chrome')
    if not exe: raise RuntimeError('Chrome/Chromium required')
    case=FeedbackTests();case.setUp()
    try:
        ffmpeg=shutil.which('ffmpeg')
        if ffmpeg:
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=teal:s=320x180:r=24','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(case.root/'test.mp4')],check=True)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=exe,headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(case.origin+'/');page.get_by_label('Your name',exact=False).fill('Synthetic Browser Reviewer');page.get_by_label('I agree to provide feedback',exact=False).check()
                page.get_by_role('button',name='Begin review',exact=False).click()
                page.wait_for_selector('#workspace:not([hidden])');page.wait_for_selector('#rating-form')
                for width in (390,768,1440):
                    page.set_viewport_size({'width':width,'height':1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
                page.get_by_label('usefulness 4 — Very useful',exact=True).check()
                page.get_by_label('accuracy 3 — Mixed',exact=True).check()
                page.locator('#rating-form textarea[name=comment]').fill('Synthetic browser feedback; never a participant result.')
                with page.expect_response(lambda r:r.url.endswith('/api/reviews') and r.request.method=='POST') as response:
                    page.get_by_role('button',name='Save & next aspect',exact=False).click()
                assert response.value.status==200
                expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                page.reload();expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                assert len(case.server.store.rows())==1
                page.goto(case.origin+'/#owner='+case.server.owner_key)
                page.wait_for_selector('#owner:not([hidden])');page.wait_for_selector('.stat-card')
                assert '1' in page.locator('#owner-stats').inner_text()
                with page.expect_download() as download:
                    page.get_by_role('button',name='Export CSV',exact=True).click()
                assert download.value.suggested_filename=='strokesense-feedback.csv'
                page.on('dialog',lambda d:d.accept())
                page.get_by_role('button',name='Withdraw my feedback',exact=True).click()
                page.wait_for_selector('#welcome:not([hidden])')
                assert case.server.store.rows()==[]
                assert not errors,errors
                print(json.dumps({'browser':browser.version,'viewports':[390,768,1440],'save_resume_export_withdraw':'passed','synthetic_feedback_only':True}))
            finally:browser.close()
    finally:case.doCleanups()

if __name__=='__main__':main()
