"""Native library removal smoke test: synthetic upload, no inference or network assets."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.library import create_server
from strokesense.registry import list_clips


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('google-chrome') or shutil.which('chromium')
    if executable is None:
        raise RuntimeError('An installed Chrome/Chromium is required')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); db = root / 'clips.db'; uploads = root / 'uploads'
        source = root / 'synthetic.mp4'
        source.write_bytes(b'\x00\x00\x00\x18ftypisom' + b'\x00' * 12)
        with JobQueue(registry_db=db, job_db=root/'jobs.db', results_root=root/'results',
                      analyze_fn=lambda *a, **k: None) as jobs:
            with create_server(jobs, registry_db=db, upload_dir=uploads, port=0) as server:
                thread = threading.Thread(target=server.serve_forever,
                    kwargs={'poll_interval': .01}, daemon=True)
                thread.start(); origin = f'http://127.0.0.1:{server.server_address[1]}'
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(executable_path=executable, headless=True)
                        try:
                            page = browser.new_page(java_script_enabled=False)
                            page.set_default_timeout(10000)
                            def upload():
                                assert page.goto(origin+'/').status == 200
                                form = page.locator('form[action="/upload"]')
                                form.locator('[name=video]').set_input_files(str(source))
                                form.locator('[name=permission]').check()
                                form.locator('[name=provenance]').fill('Synthetic permission fixture')
                                form.locator('[name=analyze]').uncheck()
                                with page.expect_response(lambda r:r.url==origin+'/upload' and r.request.method=='POST') as post:
                                    form.locator('button[type=submit]').click()
                                assert post.value.status == 303
                                page.wait_for_url(origin+'/')
                            upload()
                            row = list_clips(db, show_paths=True)[0]
                            saved = Path(row['source_path'])
                            page.locator('form[action="/revoke"] button').click()
                            page.wait_for_url(origin+'/')
                            page.get_by_role('link', name='Manage library', exact=True).click()
                            page.wait_for_url(origin+'/library')
                            assert 'Denied' in page.locator('main').inner_text()
                            assert page.get_by_role('link', name='Choose rowers', exact=True).count() == 0
                            for width in (320,390,1280):
                                page.set_viewport_size({'width':width,'height':900})
                                box = page.locator('section.history-card').bounding_box()
                                assert box and box['x'] >= -1 and box['x']+box['width'] <= width+1
                            screenshot_dir = os.environ.get('STROKESENSE_TEST_SCREENSHOTS')
                            if screenshot_dir:
                                Path(screenshot_dir).mkdir(parents=True,exist_ok=True)
                                page.screenshot(path=str(Path(screenshot_dir)/'library.png'),full_page=True)
                            page.get_by_role('link',name='Remove from library…').click()
                            assert 'Confirm removal' in page.locator('h1').inner_text()
                            assert not page.locator('[name=confirm]').is_checked()
                            page.get_by_role('link',name='Cancel',exact=True).click()
                            assert saved.exists() and len(list_clips(db)) == 1
                            page.get_by_role('link',name='Remove from library…').click()
                            page.locator('[name=confirm]').check()
                            with page.expect_response(lambda r:r.url==origin+'/library/remove' and r.request.method=='POST') as post:
                                page.get_by_role('button',name='Remove saved clip').click()
                            assert post.value.status == 303
                            page.wait_for_url(origin+'/library?removed=1')
                            assert 'Your library is empty' in page.locator('main').inner_text()
                            assert not saved.exists() and source.exists() and not list_clips(db)
                            upload()
                            assert len(list_clips(db)) == 1 and jobs.list_recent() == []
                            print(json.dumps({'browser':browser.version,'viewports':[320,390,1280],
                                'revoked_entry_visible':True,'cancel_preserves':True,
                                'confirmed_remove':303,'reimport':303,'synthetic_only':True}))
                        finally:
                            browser.close()
                finally:
                    server.shutdown();thread.join(timeout=3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
