"""HTTPS browser journey against the real hosted gateway; synthetic data only."""
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
from test_hosted import package, OWNER, INVITE


def main():
    from playwright.sync_api import sync_playwright, expect
    exe=shutil.which('google-chrome') or shutil.which('chromium')
    if not exe:raise RuntimeError('Native Chrome required')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);z=root/'fixture.zip';z.write_bytes(package())
        key=root/'tls.key';cert=root/'tls.crt'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
          '-out',str(cert),'-days','1','-subj','/CN=127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'https://127.0.0.1:{port}'
        env=dict(os.environ,STROKESENSE_DATA_DIR=str(root/'data'),STROKESENSE_PUBLIC_ORIGIN=origin,
                 STROKESENSE_OWNER_KEY=OWNER,STROKESENSE_REVIEW_CODE=INVITE)
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
                try:
                    page=browser.new_page(ignore_https_errors=True)
                    page.goto(origin+'/setup');page.get_by_label('Owner key',exact=False).fill(OWNER)
                    page.get_by_label('Complete study ZIP',exact=False).set_input_files(str(z))
                    page.get_by_role('button',name='Upload and initialize study').click()
                    expect(page.locator('#status')).to_contain_text('1 clips installed',timeout=15000)
                    page.goto(origin+'/library');page.get_by_label('Your name',exact=False).fill('Synthetic Reviewer')
                    page.get_by_label('I agree to provide feedback',exact=False).check()
                    page.get_by_role('button',name='Begin review',exact=False).click()
                    page.wait_for_selector('#reports-library:not([hidden])')
                    page.get_by_role('link',name='Review video',exact=True).click()
                    page.wait_for_selector('#workspace:not([hidden])')
                    page.get_by_label('usefulness 4 — Very useful',exact=True).check()
                    page.get_by_label('accuracy 3 — Mixed',exact=True).check()
                    page.get_by_role('button',name='Save & next aspect',exact=False).click()
                    expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                    page.locator('#submit-video').click()
                    expect(page.locator('#submit-video-status')).to_contain_text('Submitted')
                    page.reload();expect(page.locator('#progress')).to_have_text('1 / 6 saved')
                    page.goto(origin+'/#owner='+OWNER);page.wait_for_selector('#owner:not([hidden])')
                    with page.expect_download() as dl:page.get_by_role('button',name='Export CSV',exact=True).click()
                    assert dl.value.suggested_filename=='strokesense-feedback.csv'
                    print(json.dumps({'https_setup_invitation_consent_save_restore_export':'passed','browser':browser.version,
                      'synthetic_media_and_feedback':True,'render_deployed':False}))
                finally:browser.close()
        finally:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            proc.stderr.close()

if __name__=='__main__':main()
