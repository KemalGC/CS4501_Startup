"""Native four-question review/save/reload/export/withdraw, synthetic only."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_feedback import FeedbackTests
from strokesense.feedback_quality import QualityStore


def main():
 from playwright.sync_api import sync_playwright, expect
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
    expect(page.locator('#quality-state')).to_have_text('No quality assessment saved yet')
    assert page.locator('#quality-form select').count()==4
    assert all(v=='' for v in page.locator('#quality-form select').evaluate_all('(els)=>els.map(x=>x.value)'))
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':1000})
     assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1'), json.dumps(page.evaluate("""() => ({
      viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
      overflowingElements: Array.from(document.querySelectorAll('body *')).map(element => {
       const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
       return {tag: element.tagName, id: element.id, classes: String(element.className),
        left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width),
        minWidth: style.minWidth, display: style.display, whiteSpace: style.whiteSpace};
      }).filter(item => item.width > 0 && (item.right > innerWidth + 1 || item.left < -1)).slice(0, 12)
     })"""))
    for key in ('clarity','specificity','completeness','actionability'):
     page.locator('#quality-form [name='+key+']').select_option('4')
    page.locator('#quality-form [name=completeness]').select_option('cannot_judge')
    page.locator('#quality-form [name=comment]').fill('Synthetic four-question test, not a participant.')
    with page.expect_response(lambda r:r.url.endswith('/api/quality') and r.request.method=='POST') as saved:
     page.get_by_role('button',name='Save quality assessment').click()
    assert saved.value.status==200
    expect(page.locator('#quality-state')).to_have_text('All quality answers saved')
    assert len(QualityStore(case.server.store).rows())==4
    page.reload();expect(page.locator('#quality-state')).to_have_text('Saved · edits replace this assessment')
    assert page.locator('#quality-form [name=clarity]').input_value()=='4'
    assert page.locator('#quality-form [name=completeness]').input_value()=='cannot_judge'
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
    print(json.dumps({'browser':browser.version,'quality_questions':4,'viewports':[320,390,768,1440],'save_resume_export_withdraw':'passed','synthetic_feedback_only':True}))
   finally:browser.close()
 finally:case.doCleanups()

if __name__=='__main__':main()
