"""Native task selection and eight-rower confirmation; synthetic fixture only."""
from pathlib import Path
import json
import os
import shutil
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_blade_web import BladeWebTests


def main():
    from playwright.sync_api import sync_playwright
    executable=shutil.which('google-chrome') or shutil.which('chromium')
    if not executable:raise RuntimeError('Chrome required')
    case=BladeWebTests();case.setUp()
    try:
        with patch.dict(os.environ,{'STROKESENSE_CREW_MODEL':'test-local:1'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=executable,headless=True)
            try:
                page=browser.new_page(viewport={'width':1280,'height':900})
                assert page.goto(case.origin+'/crew?clip='+case.cid).status==200
                page.wait_for_function("document.querySelector('#crew-canvas').width===128")
                assert case.jobs.list_recent()==[]
                for width in (320,390,1280):
                    page.set_viewport_size({'width':width,'height':900})
                    b=page.locator('#crew-canvas').bounding_box();assert b['x']>=0 and b['x']+b['width']<=width+1
                for i in range(8):
                    page.get_by_label('R'+str(i+1)+' X',exact=True).fill(str(round((i+1)/9,3)))
                    page.get_by_label('R'+str(i+1)+' Y',exact=True).fill('0.5')
                assert page.locator('#crew-count').inner_text()=='8 of 8 selected'
                page.locator('[name=confirm]').check()
                page.locator('[name=analysis][value=rate]').check()
                assert not page.locator('[name=confirm]').is_checked()
                page.locator('[name=analysis][value=rate]').uncheck()
                page.locator('[name=analysis][value=position]').uncheck()
                assert page.get_by_role('button',name='Analyze selected tasks').is_disabled()
                page.locator('[name=analysis][value=position]').check()
                page.locator('[name=confirm]').check()
                with page.expect_response(lambda r:r.url==case.origin+'/crew' and r.request.method=='POST') as posted:
                    page.get_by_role('button',name='Analyze selected tasks').click()
                assert posted.value.status==303
                page.wait_for_url(case.origin+'/jobs/*');case.jobs.wait(page.url.rsplit('/',1)[-1],timeout=5)
                assert case.seen[0]['analyses']==['position'] and len(case.seen[0]['seeds'])==8
                print(json.dumps({'browser':browser.version,'tasks':['position'],'rowers':8,'fake_analyzer':True}))
            finally:browser.close()
    finally:case.doCleanups()


if __name__=='__main__':main()
