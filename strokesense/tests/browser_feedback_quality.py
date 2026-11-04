"""Native five-question review/save/reload/export/withdraw, synthetic only."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_feedback import FeedbackTests
from strokesense.feedback_quality import QualityStore


def main():
 from playwright.sync_api import sync_playwright
 exe=shutil.which('chromium') or shutil.which('google-chrome')
 if not exe:raise RuntimeError('Chrome required')
 case=FeedbackTests();case.setUp()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=exe,headless=True)
   try:
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(case.origin+'/');page.get_by_label('I agree to provide feedback',exact=False).check()
    page.get_by_role('button',name='Begin review',exact=False).click()
    page.wait_for_selector('#quality-panel:not([hidden])')
    page.wait_for_function("document.querySelector('#quality-state').textContent === 'No quality assessment saved yet'")
    assert page.locator('#quality-form select').count()==5
    assert all(v=='' for v in page.locator('#quality-form select').evaluate_all('(els)=>els.map(x=>x.value)'))
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':1000})
     assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
    for key in ('clarity','specificity','completeness','evidence_support','actionability'):
     page.locator('#quality-form [name='+key+']').select_option('4')
    page.locator('#quality-form [name=evidence_support]').select_option('cannot_judge')
    page.locator('#quality-form [name=comment]').fill('Synthetic five-question test, not a participant.')
    with page.expect_response(lambda r:r.url.endswith('/api/quality') and r.request.method=='POST') as saved:
     page.get_by_role('button',name='Save quality assessment').click()
    assert saved.value.status==200
    page.wait_for_function("document.querySelector('#quality-state').textContent === 'All five quality answers saved'")
    assert len(QualityStore(case.server.store).rows())==5
    page.reload();page.wait_for_function("document.querySelector('#quality-state').textContent.startsWith('Saved')")
    assert page.locator('#quality-form [name=clarity]').input_value()=='4'
    assert page.locator('#quality-form [name=evidence_support]').input_value()=='cannot_judge'
    assert case.server.store.rows()==[]
    page.goto(case.origin+'/#owner='+case.server.owner_key)
    page.wait_for_selector('#owner:not([hidden])')
    with page.expect_download() as download:
     page.get_by_role('button',name='Quality ratings CSV',exact=True).click()
    assert download.value.suggested_filename=='strokesense-quality.csv'
    page.on('dialog',lambda d:d.accept())
    page.get_by_role('button',name='Withdraw my feedback',exact=True).click()
    page.wait_for_selector('#welcome:not([hidden])')
    assert QualityStore(case.server.store).rows()==[]
    assert page.locator('#quality-panel').is_hidden()
    assert not errors,errors
    print(json.dumps({'browser':browser.version,'quality_questions':5,'viewports':[320,390,768,1440],'save_resume_export_withdraw':'passed','synthetic_feedback_only':True}))
   finally:browser.close()
 finally:case.doCleanups()

if __name__=='__main__':main()
