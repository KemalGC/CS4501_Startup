"""Native duplicate-upload recovery; generated AVI and fake analysis only."""
from pathlib import Path
import json
import os
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
    with tempfile.TemporaryDirectory(prefix='upload-recovery-') as tmp:
        root = Path(tmp)
        source = root / 'synthetic.avi'
        db = root / 'clips.db'
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 15, (640, 360))
        assert writer.isOpened()
        frame = np.zeros((360, 640, 3), np.uint8)
        for i in range(8):
            cv2.rectangle(frame, (60 + i * 65, 90), (86 + i * 65, 190), (70, 200, 230), -1)
        for _ in range(15):
            writer.write(frame)
        writer.release()
        calls = []

        def fake_analyze(video, *, out_dir, selection=None):
            calls.append(selection)
            report = out_dir / 'report.html'
            report.write_text('<h1>Synthetic analysis only</h1>')
            return {'report': report}

        with JobQueue(registry_db=db, job_db=root / 'jobs.db',
                      results_root=root / 'results', analyze_fn=fake_analyze) as jobs:
            with create_server(jobs, registry_db=db, upload_dir=root / 'uploads', port=0) as server:
                thread = threading.Thread(target=server.serve_forever,
                                          kwargs={'poll_interval': .01}, daemon=True)
                thread.start()
                origin = f'http://127.0.0.1:{server.server_address[1]}'
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(executable_path=executable, headless=True)
                        try:
                            page = browser.new_page()
                            page.set_default_timeout(10000)
                            assert page.goto(origin + '/').status == 200

                            def upload(note, camera, analyze):
                                form = page.locator('form[action="/upload"]')
                                form.locator('[name=video]').set_input_files(str(source))
                                form.locator('[name=permission]').check()
                                form.locator('[name=provenance]').fill(note)
                                form.locator('[name=camera]').select_option(camera)
                                form.locator('[name=analyze]').set_checked(analyze)
                                with page.expect_response(lambda r: r.url == origin + '/upload'
                                                          and r.request.method == 'POST') as posted:
                                    form.locator('button[type=submit]').click()
                                return posted.value.status

                            assert upload('Original synthetic attestation', '', False) == 303
                            page.wait_for_url(origin + '/')
                            before = list_clips(db, show_paths=True)
                            assert len(before) == 1
                            # Both common repeat-upload conflicts must have a usable recovery action.
                            for note, camera, expected in (
                                ('das', 'side-on', 'permission source differs'),
                                ('Original synthetic attestation', 'side-on', 'camera viewpoint differs'),
                            ):
                                assert upload(note, camera, True) == 422
                                page.wait_for_url(origin + '/upload')
                                assert expected in page.locator('[role=alert]').inner_text()
                                assert calls == [] and jobs.list_recent() == []
                                assert list_clips(db, show_paths=True) == before
                                link = page.get_by_role('link', name='Choose rowers for saved clip')
                                for width in (320, 390, 1280):
                                    page.set_viewport_size({'width': width, 'height': 900})
                                    bounds = link.bounding_box()
                                    assert bounds and bounds['x'] >= -1
                                    assert bounds['x'] + bounds['width'] <= width + 1
                                screenshots = os.environ.get('STROKESENSE_TEST_SCREENSHOTS')
                                if screenshots:
                                    folder = Path(screenshots)
                                    folder.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(folder / 'upload-recovery.png'), full_page=True)
                                link.click()
                                page.wait_for_url(origin + '/select?clip=*')
                                assert page.locator('#crew-canvas').count() == 1
                                assert calls == []
                                assert page.goto(origin + '/').status == 200
                            # Follow the recovery path through actual form submission, not only GET.
                            assert upload('Changed synthetic attestation', '', True) == 422
                            page.get_by_role('link', name='Choose rowers for saved clip').click()
                            page.wait_for_url(origin + '/select?clip=*')
                            for name, value in {'left': 4, 'top': 12, 'right': 96, 'bottom': 70}.items():
                                page.locator(f'[name={name}]').fill(str(value))
                            for i in range(8):
                                page.locator(f'[name=x{i}]').fill(str((73 + i * 65) / 640 * 100))
                                page.locator(f'[name=y{i}]').fill(str(140 / 360 * 100))
                            page.locator('[name=same_boat]').check()
                            page.get_by_role('button', name='Analyze selected crew').click()
                            page.wait_for_url(origin + '/jobs/*')
                            job = page.url.rsplit('/', 1)[-1]
                            assert jobs.wait(job, timeout=5)['status'] == 'succeeded'
                            assert len(calls) == 1 and len(calls[0]['seeds']) == 8
                            assert list_clips(db, show_paths=True) == before
                            assert len(list((root / 'uploads').iterdir())) == 1
                            print(json.dumps({'browser': browser.version, 'viewports': [320, 390, 1280],
                                'duplicate_provenance_and_camera': '422 with working recovery',
                                'original_record_unchanged': True, 'selection_submit': 'passed',
                                'selected_count': 8, 'fake_analyzer_only': True}))
                        finally:
                            browser.close()
                finally:
                    server.shutdown()
                    thread.join(3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
