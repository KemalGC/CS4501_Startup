"""Native confirmation UI with synthetic first-frame boxes; no real inference."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from strokesense import auto_selection
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('google-chrome') or shutil.which('chromium')
    if not executable:
        raise RuntimeError('Installed Chrome/Chromium is required')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); video = root/'synthetic.avi'; db = root/'clips.db'; seen = []
        frame = np.zeros((360, 640, 3), np.uint8)
        boxes = np.array([[35+i*72, y, 67+i*72, y+60] for y in (50, 230) for i in range(8)], float)
        for l,t,r,b in boxes.astype(int):
            cv2.rectangle(frame, (l,t), (r,b), (100,200,220), -1)
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 15, (640,360))
        assert writer.isOpened()
        for _ in range(15): writer.write(frame)
        writer.release()
        proposals = auto_selection.detect_candidates(frame, lambda *a, **kw: (boxes, np.ones(16), np.ones((16,17,3))))
        clip = register_clip(video, db, permission='granted', provenance='Synthetic browser fixture')[0]
        def fake_analyze(video, *, out_dir, selection=None):
            seen.append(selection)
            report = out_dir/'report.html'; report.write_text('<h1>Synthetic selected report</h1>')
            return {'report': report}
        with patch.object(auto_selection, 'suggest', return_value=proposals):
            with JobQueue(registry_db=db, job_db=root/'jobs.db', results_root=root/'results', analyze_fn=fake_analyze) as jobs:
                with create_server(jobs, registry_db=db, port=0) as server:
                    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
                    thread.start(); origin = f'http://127.0.0.1:{server.server_address[1]}'
                    try:
                        with sync_playwright() as pw:
                            browser = pw.chromium.launch(executable_path=executable, headless=True)
                            try:
                                page = browser.new_page(viewport={'width':1280,'height':900}, reduced_motion='reduce')
                                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                                assert page.goto(origin+'/select?clip='+clip['clip_id']).status == 200
                                page.wait_for_function("document.querySelector('#crew-canvas').width === 640")
                                toggles = page.locator('.person-toggle'); submit = page.get_by_role('button', name='Analyze selected crew')
                                assert toggles.count() == 16 and page.locator('.person-toggle:checked').count() == 0
                                assert submit.is_disabled() and jobs.list_recent() == []
                                for width in (320,390,1280):
                                    page.set_viewport_size({'width':width,'height':900})
                                    rect = page.locator('#crew-canvas').bounding_box()
                                    assert rect['x'] >= -1 and rect['x']+rect['width'] <= width+1
                                for i in range(7): toggles.nth(i).check()
                                assert submit.is_disabled() and jobs.list_recent() == []
                                toggles.nth(7).check()
                                assert submit.is_enabled() and '8 of 8' in page.locator('#candidate-count').inner_text()
                                toggles.nth(8).click()
                                assert not toggles.nth(8).is_checked() and page.locator('.person-toggle:checked').count() == 8
                                page.locator('[name=same_boat]').check()
                                toggles.nth(7).uncheck()
                                assert submit.is_disabled() and not page.locator('[name=same_boat]').is_checked()
                                toggles.nth(7).check()
                                page.get_by_role('button', name='Reset selection').click()
                                assert page.locator('.person-toggle:checked').count() == 0 and submit.is_disabled()
                                # Test a canvas click as well as keyboard/native checkbox controls.
                                canvas = page.locator('#crew-canvas'); rect = canvas.bounding_box()
                                canvas.click(position={'x':51/640*rect['width'], 'y':80/360*rect['height']})
                                assert toggles.nth(0).is_checked()
                                for i in range(1,8): toggles.nth(i).check()
                                page.locator('[name=same_boat]').check()
                                with page.expect_response(lambda r: r.url == origin+'/select' and r.request.method == 'POST') as posted:
                                    submit.click()
                                assert posted.value.status == 303
                                page.wait_for_url(origin+'/jobs/*')
                                job_id = page.url.rsplit('/',1)[-1]
                                assert jobs.wait(job_id, timeout=5)['status'] == 'succeeded'
                                assert len(seen) == 1 and jobs.selection(job_id) == seen[0]
                                assert seen[0]['roi'] == [0,0,1,1]
                                np.testing.assert_allclose(seen[0]['seeds'], [c['seed'] for c in proposals['candidates'][:8]], atol=1e-5)
                                assert not errors, errors
                                # Manual fallback remains usable after returning to the preview.
                                page.goto(origin+'/select?clip='+clip['clip_id'])
                                page.get_by_role('button', name='Use manual selection').click()
                                assert not page.locator('#detected-people').is_visible()
                                assert not page.get_by_role('button', name='Analyze selected crew').is_disabled()
                                print(json.dumps({'browser':browser.version, 'automatic_candidates':16,
                                    'selected_same_fixture_boat':8, 'unconfirmed_jobs':0, 'confirmed_jobs':1,
                                    'viewports':[320,390,1280], 'manual_fallback':True, 'synthetic_detector_and_analyzer':True}))
                            finally: browser.close()
                    finally: server.shutdown(); thread.join(3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
