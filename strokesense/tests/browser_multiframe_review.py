"""Native later-frame/boat confirmation using synthetic proposals, not inference."""
from pathlib import Path
import base64
import json
import shutil
import sys
import tempfile
import threading
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server
from strokesense.review import add_review


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('google-chrome') or shutil.which('chromium')
    if not executable:
        raise RuntimeError('Installed Chrome/Chromium is required')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        video = root / 'synthetic.avi'
        image = np.zeros((360, 640, 3), np.uint8)
        boxes = [[35+i*72, y, 67+i*72, y+60] for y in (50, 230) for i in range(8)]
        for left, top, right, bottom in boxes:
            cv2.rectangle(image, (left, top), (right, bottom), (100, 200, 220), -1)
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 15, (640, 360))
        assert writer.isOpened()
        for _ in range(45):
            writer.write(image)
        writer.release()
        jpeg = cv2.imencode('.jpg', image)[1]
        uri = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()
        candidates = [{'id':i+1, 'box':np.array(b).astype(float).tolist(),
                       'seed':[(b[0]+b[2])/2/640, (b[1]+b[3])/2/360]}
                      for i, b in enumerate(boxes)]
        for c in candidates:
            c['box'] = (np.array(c['box'])/[640,360,640,360]).tolist()
        boats = [{'id':i+1, 'members':list(range(i*8, i*8+8)),
                  'box':[.03, .10+i*.5, .95, .40+i*.5],
                  'kind':'rower_alignment_proposal'} for i in range(2)]
        def scan(path):
            return {'state':'ready', 'selected':[], 'frames':[
                {'seconds':0.0, 'image':uri, 'candidates':candidates[:6], 'boats':[]},
                {'seconds':1.0, 'image':uri, 'candidates':candidates, 'boats':boats}]}
        db = root / 'clips.db'
        clip = register_clip(video, db, permission='granted', provenance='Synthetic browser test')[0]
        seen = []
        def analyze(path, *, out_dir, selection=None):
            seen.append(selection)
            result = out_dir / 'report.html'
            result.write_text('<h1>Synthetic review run</h1>')
            return {'report':result}
        with JobQueue(registry_db=db, job_db=root/'jobs.db', results_root=root/'results', analyze_fn=analyze) as jobs:
            with add_review(create_server(jobs, registry_db=db, port=0), jobs, db, scan_fn=scan) as server:
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
                thread.start()
                origin = f'http://127.0.0.1:{server.server_address[1]}'
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(executable_path=executable, headless=True)
                        try:
                            page = browser.new_page(viewport={'width':1280,'height':900}, reduced_motion='reduce')
                            errors = []
                            page.on('pageerror', lambda err: errors.append(str(err)))
                            assert page.goto(origin+'/review?clip='+clip['clip_id']).status == 200
                            page.wait_for_function("document.querySelectorAll('.review-person').length === 16")
                            assert jobs.list_recent() == []
                            assert page.locator('.review-person:checked').count() == 0
                            canvas = page.locator('#review-canvas')
                            page.wait_for_function("document.querySelector('#review-canvas').width === 640")
                            for width in (320, 390, 1280):
                                page.set_viewport_size({'width':width,'height':900})
                                bounds = canvas.bounding_box()
                                assert bounds['x'] >= -1 and bounds['x']+bounds['width'] <= width+1
                            page.get_by_role('button', name='0.00 s · 6 people', exact=True).click()
                            assert page.locator('.review-person').count() == 6
                            assert page.get_by_role('button', name='Analyze confirmed crew').is_disabled()
                            page.get_by_role('button', name='1.00 s · 16 people', exact=True).click()
                            page.get_by_role('button', name='Suggested boat 2 · 8 people', exact=True).click()
                            toggles = page.locator('.review-person')
                            assert toggles.count() == 8
                            for i in range(8):
                                toggles.nth(i).check()
                            assert page.locator('.review-person:checked').count() == 8
                            page.locator('[name=same_boat]').check()
                            toggles.nth(7).uncheck()
                            assert not page.locator('[name=same_boat]').is_checked()
                            assert page.get_by_role('button', name='Analyze confirmed crew').is_disabled()
                            toggles.nth(7).check()
                            page.locator('[name=same_boat]').check()
                            assert jobs.list_recent() == []
                            with page.expect_response(lambda r: r.url==origin+'/review/confirm' and r.request.method=='POST') as posted:
                                page.get_by_role('button', name='Analyze confirmed crew').click()
                            assert posted.value.status == 303
                            page.wait_for_url(origin+'/jobs/*')
                            job = jobs.wait(page.url.rsplit('/',1)[-1], timeout=5)
                            assert job['status']=='succeeded' and len(seen)==1
                            assert seen[0]['version']==2 and seen[0]['reference_seconds']==1
                            assert seen[0]['seeds']==[c['seed'] for c in candidates[8:]]
                            assert not errors, errors
                            print(json.dumps({'browser':browser.version,'viewports':[320,390,1280],
                                'later_reference_seconds':1,'confirmed_second_boat':8,
                                'first_frame_only_six':True,'synthetic_proposals_and_analyzer':True}))
                        finally:
                            browser.close()
                finally:
                    server.shutdown()
                    thread.join(3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
