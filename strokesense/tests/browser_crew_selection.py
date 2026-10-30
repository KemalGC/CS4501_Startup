"""Native form/canvas regression with a generated AVI and fake analyzer.

No private video, real pose inference, or automatic boat-membership validation.
"""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from strokesense.jobs import JobQueue
from strokesense.registry import list_clips
from strokesense.web import create_server


def main():
    from playwright.sync_api import sync_playwright
    executable = shutil.which('google-chrome') or shutil.which('chromium')
    if not executable:
        raise RuntimeError('Installed Chrome/Chromium is required')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); video=root/'synthetic.avi'; db=root/'clips.db'; seen=[]
        writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(640,360))
        assert writer.isOpened()
        image=np.zeros((360,640,3),np.uint8)
        for i in range(8):cv2.rectangle(image,(60+i*65,90),(86+i*65,190),(70,200,230),-1)
        for _ in range(15):writer.write(image)
        writer.release()
        def fake_analyze(video,*,out_dir,selection=None):
            seen.append(selection)
            output=out_dir/'report.html';output.write_text('<h1>Synthetic selected run</h1>')
            return {'report':output}
        with JobQueue(registry_db=db,job_db=root/'jobs.db',results_root=root/'results',analyze_fn=fake_analyze) as jobs:
            with create_server(jobs,registry_db=db,port=0) as server:
                thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
                thread.start();origin=f'http://127.0.0.1:{server.server_address[1]}'
                try:
                    with sync_playwright() as pw:
                        browser=pw.chromium.launch(executable_path=executable,headless=True)
                        try:
                            page=browser.new_page(); errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            assert page.goto(origin+'/').status==200
                            form=page.locator('form[action="/upload"]')
                            assert form.locator('[name=select_crew]').is_checked()
                            form.locator('[name=video]').set_input_files(str(video))
                            form.locator('[name=permission]').check()
                            form.locator('[name=provenance]').fill('Synthetic browser regression')
                            form.locator('button[type=submit]').click()
                            page.wait_for_url(origin+'/select?clip=*')
                            assert jobs.list_recent()==[], 'Import must not start inference before selection'
                            canvas=page.locator('#crew-canvas')
                            page.wait_for_function("document.querySelector('#crew-canvas').width === 640")
                            for width in (320,390,1280):
                                page.set_viewport_size({'width':width,'height':900})
                                box=canvas.bounding_box()
                                assert box['x']>=-1 and box['x']+box['width']<=width+1
                            def click(x,y):
                                box=canvas.bounding_box()
                                canvas.click(position={'x':x*box['width'],'y':y*box['height']})
                            click(.04,.12);click(.96,.7)
                            for i in range(8):click((73+i*65)/640,140/360)
                            assert '8 of 8' in page.locator('#selection-progress').inner_text()
                            page.locator('[name=same_boat]').check()
                            with page.expect_response(lambda r:r.url==origin+'/select' and r.request.method=='POST') as posted:
                                page.get_by_role('button',name='Analyze selected crew').click()
                            assert posted.value.status==303
                            page.wait_for_url(origin+'/jobs/*')
                            jobid=page.url.rsplit('/',1)[-1]
                            assert jobs.wait(jobid,timeout=5)['status']=='succeeded'
                            assert len(seen)==1 and len(seen[0]['seeds'])==8 and seen[0]['confirmed_same_boat']
                            assert jobs.selection(jobid)==seen[0]
                            assert not errors,errors
                            print(json.dumps({'browser':browser.version,'viewports':[320,390,1280],
                                'import_paused_for_selection':True,'selected_count':8,'http':posted.value.status,
                                'fake_analyzer_only':True}))
                        finally:browser.close()
                finally:server.shutdown();thread.join(3)
    return 0

if __name__=='__main__':raise SystemExit(main())
