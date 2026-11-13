"""Chrome integration: fictional media/review and fake generator, no real LLM."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_review_demo import ReviewDemoTests
from strokesense.review_demo import create_server


def main():
    fixture = ReviewDemoTests()
    fixture.setUp()
    servers = []
    try:
        writer = cv2.VideoWriter(str(fixture.video), cv2.VideoWriter_fourcc(*'mp4v'), 15, (320, 180))
        for _ in range(90):
            writer.write(np.full((180, 320, 3), (50, 85, 70), dtype=np.uint8))
        writer.release()
        import hashlib
        fixture.manifest['video_sha256'] = hashlib.sha256(fixture.video.read_bytes()).hexdigest()
        fixture.save_review()
        bad = copy.deepcopy(fixture.candidate)
        bad['observed_count'] = 99
        fixture.generator.side_effect = [bad, fixture.candidate]
        sessions = [fixture.session(), fixture.session(review_path=None, mode='disabled')]
        for session in sessions:
            server = create_server(session, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            servers.append((server, thread))
        output = Path(__file__).resolve().parents[2] / 'artifacts' / 'review-demo'
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{servers[0][0].server_address[1]}/')
            page.get_by_text('Test double:', exact=False).wait_for()
            page.get_by_text('Ready to generate a coaching draft.', exact=True).wait_for()
            page.get_by_role('button', name='Generate coaching draft').click()
            page.get_by_text('Reference and quantity checks passed.', exact=False).wait_for()
            assert page.locator('#draft').inner_text() == fixture.candidate['explanation']
            assert 'Attempts: 2' in page.locator('#facts').inner_text()
            assert page.get_by_role('button', name='Generate coaching draft').is_disabled()
            assert page.locator('#evidence a').count() == 2
            page.locator('#evidence a').first.click()
            assert abs(page.locator('video').evaluate('(v) => v.currentTime') - 10 / 15) < .1
            with page.expect_popup() as popup:
                page.get_by_role('link', name="Open this clip's saved analysis report").click()
            assert 'Synthetic fixture report' in popup.value.locator('body').inner_text()
            popup.value.close()
            page.screenshot(path=str(output / 'checked-test-double.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(output / 'mobile-test-double.png'), full_page=True)
            page.goto(f'http://127.0.0.1:{servers[1][0].server_address[1]}/')
            page.get_by_text('Withheld: genuine review', exact=False).wait_for()
            assert page.get_by_role('button', name='Generate coaching draft').is_disabled()
            assert page.locator('#draft').inner_text() == ''
            page.screenshot(path=str(output / 'withheld-no-review.png'), full_page=True)
            assert not errors, errors
            browser.close()
        print(json.dumps({'browser': 'Chrome', 'result': 'passed',
                          'scope': 'synthetic connected UI and withholding; no real LLM or human approval',
                          'screenshots': str(output)}))
    finally:
        for server, thread in servers:
            server.shutdown(); thread.join(3); server.server_close()
        fixture.doCleanups()


if __name__ == '__main__':
    main()
