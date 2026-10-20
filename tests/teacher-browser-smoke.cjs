const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {mkdtempSync, mkdirSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const {randomBytes} = require('node:crypto');
const net = require('node:net');

(async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'proofgrade-browser-'));
  const password = randomBytes(24).toString('hex');
  const python = process.env.PROOFGRADE_TEST_PYTHON || 'python';
  const port = await new Promise(resolve => {
    const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
  const base = 'http://127.0.0.1:' + port;
  const env = {...process.env, PROOFGRADE_TEACHER_DB: path.join(dir, 'teacher.sqlite3'),
    PROOFGRADE_HINT_MODE: 'demo', PROOFGRADE_TEACHER_AI: 'disabled', PROOFGRADE_STORE_ATTEMPTS: 'false',
    PROOFGRADE_PDF_UPLOADS: 'false'};
  execFileSync(python, ['-c', "import os,sys; from proofgrade.teacher_store import TeacherStore; TeacherStore(os.environ['PROOFGRADE_TEACHER_DB']).create_teacher('browser-teacher',sys.stdin.read())"], {env, input: password});
  const server = spawn(python, ['tests/browser_server.py', String(port)], {env, stdio: ['ignore', 'pipe', 'pipe']});
  let serverLog = '';
  server.stderr.on('data', chunk => { serverLog += chunk; });
  let browser, page;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { ready = (await fetch(base + '/health')).ok; if (ready) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    assert(ready, 'Server did not start: ' + serverLog);
    browser = await chromium.launch({headless: true,
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
    page = await browser.newPage({viewport: {width: 1440, height: 1100}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base);
    await page.getByLabel('Username', {exact: true}).fill('browser-teacher');
    await page.getByLabel('Password', {exact: true}).fill(password);
    await page.getByRole('button', {name: 'Sign in', exact: true}).click();
    await page.getByRole('button', {name: 'Create an assignment', exact: true}).click();
    await page.getByLabel('Assignment title', {exact: true}).fill('Browser algebra check');
    await page.getByLabel('Class / tutoring group', {exact: true}).fill('Algebra 1');
    await page.getByLabel('Equation 1', {exact: true}).fill('2(x+3)=10');
    await page.getByLabel('Answer key 1', {exact: true}).fill('x=2');
    await page.getByLabel('Skill 1', {exact: true}).selectOption('distribution');
    await page.getByRole('button', {name: 'Create assignment', exact: true}).click();
    await page.getByRole('heading', {name: 'Browser algebra check', exact: true}).waitFor();
    await page.getByLabel('Anonymous student code / batch prefix').fill('student-01');
    // Browser-rendered fixture, not real handwriting or a recognition benchmark.
    const png = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 1200; canvas.height = 1600;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1200, 1600);
      ctx.fillStyle = '#243047'; ctx.font = '36px sans-serif'; ctx.fillText('Synthetic worksheet fixture', 90, 130);
      ctx.font = '48px cursive';
      ['Q1.  2(x + 3) = 10', '2x + 3 = 10', '2x = 7'].forEach((line, i) => ctx.fillText(line, 100, 300 + i * 140));
      return canvas.toDataURL('image/png').split(',')[1];
    }), 'base64');
    // Exercise resizing and transparent pixels, plus JPEG EXIF orientation below.
    const preparation = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 4000; canvas.height = 3000;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#f00'; ctx.fillRect(0, 0, 2000, 3000);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      const prepared = await ProofGradeImages.prepare(blob);
      const rgb = atob(prepared.pixels_base64);
      return {width: prepared.width, height: prepared.height, length: rgb.length,
        left: [...rgb.slice(0, 3)].map(x => x.charCodeAt(0)), right: [...rgb.slice(-3)].map(x => x.charCodeAt(0))};
    });
    assert.equal(preparation.width, 2000); assert.equal(preparation.height, 1500);
    assert.equal(preparation.length, 9_000_000);
    assert.deepEqual(preparation.left, [255, 0, 0]); assert.deepEqual(preparation.right, [255, 255, 255]);
    const jpeg = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 4; canvas.height = 2;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 4, 2);
      const bytes = new Uint8Array(await (await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg'))).arrayBuffer());
      // A minimal EXIF orientation=6 (90 degrees clockwise), between SOI and image data.
      const exif = new Uint8Array([255,225,0,34,69,120,105,102,0,0,73,73,42,0,8,0,0,0,
        1,0,18,1,3,0,1,0,0,0,6,0,0,0,0,0,0,0]);
      const prepared = await ProofGradeImages.prepare(new Blob([bytes.slice(0, 2), exif, bytes.slice(2)], {type: 'image/jpeg'}));
      let rejected = false;
      try { await ProofGradeImages.prepare(new Blob(['<svg></svg>'], {type: 'image/png'})); } catch { rejected = true; }
      return {width: prepared.width, height: prepared.height, rejected};
    });
    assert.deepEqual(jpeg, {width: 2, height: 4, rejected: true});
    await page.getByLabel('Homework files (optional)').setInputFiles({name: 'synthetic-worksheet.png', mimeType: 'image/png', buffer: png});
    const uploaded = page.waitForResponse(response => response.url().endsWith('/image-uploads') && response.status() === 201);
    await page.getByRole('button', {name: 'Add student work', exact: true}).click();
    await uploaded;
    await page.getByRole('button', {name: 'Review student-01', exact: true}).click();
    await page.getByAltText('Uploaded homework source, page 1').waitFor();
    await page.waitForFunction(() => {
      const img = document.querySelector('img[alt="Uploaded homework source, page 1"]');
      return img?.complete && img.naturalWidth > 0;
    });
    const dimensions = await page.getByAltText('Uploaded homework source, page 1').evaluate(img => [img.naturalWidth, img.naturalHeight]);
    assert.deepEqual(dimensions, [1200, 1600]);
    await page.getByRole('button', {name: 'Extract handwriting with AI', exact: true}).click();
    await page.getByText('AI transcription is a draft. Compare it with the original before confirming.', {exact: true}).waitFor();
    assert.equal(await page.getByLabel('Student steps Q1', {exact: true}).inputValue(), '2x+3=10\n2x=7');
    assert.equal(await page.getByLabel('Source for Q1', {exact: true}).inputValue(), '1');
    await page.getByAltText('Uploaded homework source, page 1').evaluate(img => img.decode());
    mkdirSync('test-results', {recursive: true});
    await page.screenshot({path: 'test-results/teacher-photo-review.png', fullPage: true});
    await page.getByLabel('I checked these equations against the source or entered the typed response.').check();
    await page.getByRole('button', {name: 'Confirm transcription & check', exact: true}).click();
    await page.getByRole('heading', {name: '2. Review suggested grades', exact: true}).waitFor();
    await page.getByText('First invalid step: 1', {exact: true}).waitFor();
    await page.getByLabel('Q1 work / 2', {exact: true}).fill('1');
    await page.getByLabel('Teacher decision / override reason Q1', {exact: true}).fill('One point for the attempted distribution, reviewed by teacher.');
    await page.getByLabel('I reviewed the scores and feedback and approve this result.').check();
    await page.getByRole('button', {name: 'Approve grades & feedback', exact: true}).click();
    await page.getByRole('heading', {name: '2. Approved grades & feedback', exact: true}).waitFor();
    const feedback = await page.request.get(base + await page.getByRole('link', {name: 'Download approved feedback'}).getAttribute('href'));
    assert((await feedback.text()).includes('Q1: 1/5'));
    await page.getByRole('button', {name: '← Back to assignment', exact: true}).click();
    await page.getByRole('button', {name: 'Create practice', exact: true}).click();
    await page.getByRole('button', {name: 'Approve practice set', exact: true}).click();
    await page.getByRole('link', {name: 'Download student practice', exact: true}).waitFor();
    const csv = await page.request.get(base + await page.getByRole('link', {name: 'Export grades'}).getAttribute('href'));
    assert((await csv.text()).includes('student-01,1,5,20.0'));
    mkdirSync('test-results', {recursive: true});
    await page.screenshot({path: 'test-results/teacher-dashboard.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Mobile layout overflows');
    await page.screenshot({path: 'test-results/teacher-mobile.png', fullPage: true});
    await page.getByRole('button', {name: 'Review student-01', exact: true}).click();
    await page.getByLabel('Student steps Q1', {exact: true}).fill('x+3=5\nx=2');
    await page.getByLabel('I checked these equations against the source or entered the typed response.').check();
    await page.getByRole('button', {name: 'Revise transcription and invalidate approval', exact: true}).click();
    await page.getByRole('heading', {name: '2. Review suggested grades', exact: true}).waitFor();
    assert.equal(await page.getByLabel('Q1 answer / 3', {exact: true}).inputValue(), '3');
    assert.equal(await page.getByLabel('Q1 work / 2', {exact: true}).inputValue(), '2');
    await page.getByRole('button', {name: '← Back to assignment', exact: true}).click();
    const cleared = await page.request.get(base + await page.getByRole('link', {name: 'Export grades'}).getAttribute('href'));
    assert(!(await cleared.text()).includes('student-01'));
    await page.reload();
    await page.getByLabel('Anonymous student code / batch prefix').fill('typed-fallback');
    assert(await page.getByLabel('Homework files (optional)').isEnabled());
    assert(!(await page.getByLabel('Homework files (optional)').getAttribute('accept')).includes('pdf'));
    await page.getByRole('button', {name: 'Add student work', exact: true}).click();
    await page.getByLabel('Student steps Q1', {exact: true}).fill('x+3=5\nx=2');
    await page.getByLabel('I checked these equations against the source or entered the typed response.').check();
    await page.getByRole('button', {name: 'Confirm transcription & check', exact: true}).click();
    await page.getByRole('heading', {name: '2. Review suggested grades', exact: true}).waitFor();
    assert.equal(await page.getByLabel('Q1 answer / 3', {exact: true}).inputValue(), '3');
    await page.getByRole('button', {name: 'Sign out', exact: true}).click();
    await page.getByRole('button', {name: 'Sign in', exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log('Teacher browser flow passed with native image libraries blocked: browser RGB upload, source PNG decoding, synthetic model extraction, source confirmation, scoring, approval, analytics, export, practice, mobile layout, revision invalidation and typed entry. Model accuracy was not measured.');
    execFileSync(process.execPath, ['tests/browser-smoke.cjs'], {env: {...process.env, PROOFGRADE_TEST_URL: base}, stdio: 'inherit'});
  } catch (error) {
    if (page) {
      mkdirSync('test-results', {recursive: true});
      await page.screenshot({path: 'test-results/teacher-failure.png', fullPage: true}).catch(() => {});
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => { if (server.exitCode !== null) resolve(); else server.on('exit', resolve); });
    rmSync(dir, {recursive: true, force: true});
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
