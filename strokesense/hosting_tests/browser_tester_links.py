"""Real HTTPS browser/MP4 playback and five isolated test reviewers, not participants."""
from pathlib import Path
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_hosted import OWNER, INVITE
from test_tester_links import ten_package


def main():
    from playwright.sync_api import sync_playwright, expect
    exe=shutil.which('google-chrome') or shutil.which('chromium')
    ffmpeg=shutil.which('ffmpeg')
    if not exe or not ffmpeg:raise RuntimeError('Native Chrome and FFmpeg are required')
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);video=root/'fixture.mp4';poster=root/'poster.jpg'
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12',
          '-t','2','-an','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
        subprocess.run([ffmpeg,'-v','error','-i',str(video),'-frames:v','1',str(poster)],check=True)
        z=root/'study.zip';z.write_bytes(ten_package(video.read_bytes(),poster.read_bytes()))
        key=root/'tls.key';cert=root/'tls.crt'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
          '-out',str(cert),'-days','1','-subj','/CN=127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        origin=f'https://127.0.0.1:{port}'
        env=dict(os.environ,STROKESENSE_DATA_DIR=str(root/'data'),STROKESENSE_PUBLIC_ORIGIN=origin,
                 STROKESENSE_OWNER_KEY=OWNER,STROKESENSE_REVIEW_CODE=INVITE,STROKESENSE_EXPECTED_CLIPS='10')
        proc=subprocess.Popen([sys.executable,'-m','uvicorn','strokesense.feedback_hosted:create_app','--factory',
          '--host','127.0.0.1','--port',str(port),'--ssl-keyfile',str(key),'--ssl-certfile',str(cert),'--no-access-log'],
          env=env,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for _ in range(80):
                if proc.poll() is not None:raise RuntimeError(proc.stderr.read().decode())
                try:
                    with urllib.request.urlopen(origin+'/healthz',context=ssl._create_unverified_context(),timeout=.5) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=exe,headless=True)
                contexts=[]
                try:
                    owner_context=browser.new_context(ignore_https_errors=True)
                    contexts.append(owner_context);owner=owner_context.new_page()
                    owner.goto(origin+'/setup');owner.get_by_label('Owner key',exact=False).fill(OWNER)
                    owner.get_by_label('Complete study ZIP',exact=False).set_input_files(str(z))
                    owner.get_by_role('button',name='Upload and initialize study').click()
                    expect(owner.locator('#status')).to_contain_text('10 clips installed')
                    owner.goto(origin+'/owner');owner.get_by_label('Private owner key').fill(OWNER)
                    owner.get_by_role('button',name='Generate tester link').click()
                    expect(owner.locator('#invitation-result')).to_be_visible()
                    link=owner.locator('#tester-link').input_value();token=link.split('#invite=',1)[1]
                    assert OWNER not in link and INVITE not in link
                    urls=[];reviewer_ids=[]
                    for i in range(1,6):
                        ctx=browser.new_context(ignore_https_errors=True,viewport={'width':390 if i==1 else 1280,'height':900})
                        contexts.append(ctx);page=ctx.new_page();page.on('request',lambda r:urls.append(r.url))
                        page.goto(link);page.wait_for_url(origin+'/library')
                        assert '#' not in page.url
                        page.get_by_label('I agree to provide feedback',exact=False).check()
                        page.get_by_role('button',name='Begin review',exact=False).click()
                        expect(page.locator('#report-cards .report-card')).to_have_count(10)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                        # Every report card must map to its own report, not the first clip.
                        if i==1:
                            for clip in range(1,11):
                                page.locator(f'.report-card[data-clip="clip-{clip}"]').get_by_role('link',name='Open report',exact=True).click()
                                expect(page.frame_locator('#report-frame').get_by_role('heading',name=f'Report for clip {clip}',exact=True)).to_be_visible()
                                page.goto(origin+'/library');expect(page.locator('.report-card')).to_have_count(10)
                        page.locator('.report-card[data-clip="clip-1"]').get_by_role('link',name='Review video',exact=True).click()
                        page.wait_for_selector('#workspace:not([hidden])')
                        if i==1:
                            for mode in ('#annotated-mode','#source-mode'):
                                page.locator(mode).click()
                                # preload=metadata is allowed to stop before loadeddata.
                                # Actually request playback, then prove decoded frames advance.
                                # Poll inside a supplied function: wait_for_function's
                                # string evaluation is blocked by the real strict CSP.
                                # Keep CSP enabled and verify actual decoded playback.
                                page.locator('#video').evaluate("""async v => {
                                  v.muted=true; v.currentTime=0; await v.play();
                                  await new Promise((resolve,reject) => {
                                    const deadline=performance.now()+10000;
                                    function check() {
                                      if(v.currentTime>0.2 && v.readyState>=2) return resolve(true);
                                      if(performance.now()>=deadline) return reject(Error('Video did not advance'));
                                      setTimeout(check,50);
                                    }
                                    check();
                                  });
                                  v.pause();
                                }""")
                                page.locator('#video').evaluate("v => new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Seek failed')),10000);v.addEventListener('seeked',()=>{clearTimeout(timer);resolve(true);},{once:true});v.currentTime=1;})")
                                assert abs(page.locator('#video').evaluate('v => v.currentTime') - 1) < .15
                        expect(page.locator('#progress')).to_have_text('0 / 6 saved')
                        expect(page.locator('#evaluation-questions select')).to_have_count(10)
                        for choice in page.locator('#evaluation-questions select').all():
                            choice.select_option('correct')
                        page.locator('[name=manual_enabled]').check()
                        page.locator('[name=catch_count]').fill('2')
                        page.locator('[name=first_catch_seconds]').fill('0.2')
                        page.locator('[name=last_catch_seconds]').fill('1.8')
                        page.locator('[name=rower_reference]').fill('Synthetic reference rower')
                        page.locator('#evaluation-save').click()
                        expect(page.locator('#evaluation-state')).to_contain_text('All ten technical judgments saved')
                        for title in ('Clarity','Specificity','Completeness','Evidence support','Actionability'):
                            expect(page.get_by_label(title+' quality',exact=True)).to_have_value('')
                            page.get_by_label(title+' quality',exact=True).select_option(str(i))
                        page.locator('#quality-save').click()
                        expect(page.locator('#quality-state')).to_have_text('All five quality answers saved')
                        page.get_by_label('usefulness 4 — Very useful',exact=True).check()
                        page.get_by_label('accuracy 3 — Mixed',exact=True).check()
                        page.get_by_role('button',name='Save & next aspect',exact=False).click()
                        expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                        page.reload();expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                        expect(page.get_by_label('Clarity quality',exact=True)).to_have_value(str(i))
                        expect(page.locator('#evaluation-questions select').first).to_have_value('correct')
                        expect(page.locator('[name=catch_count]')).to_have_value('2')
                        expect(page.locator('#evaluation-rate-preview')).to_contain_text('37.5')
                        data=ctx.request.get(origin+'/api/bootstrap').json();reviewer_ids.append(data['session']['reviewer_id'])
                        assert ctx.request.get(origin+'/api/owner/export.json').status==403
                        assert ctx.request.get(origin+'/api/owner/evaluation.json').status==403
                    assert len(set(reviewer_ids))==5
                    assert all(token not in url for url in urls)
                    # Owner authentication is independent of the reviewer invitation.
                    owner.goto(origin+'/library');owner.get_by_label('Reviewer access code').fill(OWNER)
                    owner.get_by_role('button',name='Open the review study').click()
                    owner.wait_for_selector('#welcome:not([hidden])')
                    rows=owner_context.request.get(origin+'/api/owner/quality.json',headers={'Authorization':'Bearer '+OWNER}).json()['responses']
                    assert len(rows)==25
                    technical=owner_context.request.get(origin+'/api/owner/evaluation.json',headers={'Authorization':'Bearer '+OWNER}).json()['responses']
                    assert len(technical)==5 and all(len(row['answers'])==10 for row in technical)
                    assert all(abs(row['stroke_measurement']['rate_spm']-37.5)<.001 for row in technical)
                    summary=owner_context.request.get(origin+'/api/owner/summary',headers={'Authorization':'Bearer '+OWNER}).json()
                    assert summary['reviewer_count']==5 and summary['response_count']==5
                    print(json.dumps({'https_invitation_library_report_mapping':'passed','correct_report_links':10,
                      'original_and_annotated_mp4_seek':'passed','isolated_test_reviewers':5,'quality_answers':25,
                      'aspect_answers':5,'technical_judgments':50,'manual_cadence_roundtrips':5,
                      'browser':browser.version,'synthetic_only':True,'render_live':False}))
                finally:
                    for ctx in contexts:ctx.close()
                    browser.close()
        finally:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            proc.stderr.close()

if __name__=='__main__':main()
