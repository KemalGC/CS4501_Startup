import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/library.js', import.meta.url), 'utf8');
const JOB_A = '8d323d41ed3a4ffcaee778201670098e';
const JOB_B = '87ffb753de784010900883b013649be1';

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.listeners = new Map();
    this._text = '';
    this.src = '';
  }
  set textContent(text) {
    this._text = String(text);
    this.children = [];
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this._text = ''; this.children = [...children]; }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  click() { this.listeners.get('click')?.(); }
  removeAttribute(name) { if (name === 'src') this.src = ''; }
  pause() {}
  load() {}
  set innerHTML(_value) { throw Error('History must render untrusted fields as text, never HTML.'); }
}

function makePage({ authenticated = true, responses = [] } = {}) {
  const elements = new Map();
  const storage = new Map();
  const requests = [];
  const ids = ['library-account', 'library-sign-in', 'library-refresh',
    'library-notice', 'library-list', 'library-more', 'library-video-panel',
    'library-video-player', 'library-video-title', 'library-video-notice',
    'library-close-video', 'library-refresh-video'];
  for (const id of ids) elements.set(id, new FakeElement());
  elements.get('library-more').hidden = true;
  elements.get('library-sign-in').hidden = true;
  elements.get('library-refresh').hidden = true;
  elements.get('library-list').hidden = true;
  elements.get('library-video-panel').hidden = true;
  if (authenticated) storage.set('strokesense-aws-dev-auth', JSON.stringify({
    accessToken: 'private-access-token', idToken: '', expiresAt: Date.now() + 3_600_000
  }));

  runInNewContext(source, {
    window: { STROKESENSE_AWS_CONFIG: { apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com' } },
    document: {
      getElementById: id => elements.get(id),
      createElement: name => new FakeElement(name)
    },
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const response = responses.shift();
      if (!response) throw Error('Unexpected additional network request');
      return { status: response.status || 200, ok: (response.status || 200) < 400,
        json: async () => response.payload };
    },
    URL, AbortController, setTimeout, clearTimeout, atob
  });
  return {
    elements, storage, requests,
    async settle() { await new Promise(resolve => setImmediate(resolve)); }
  };
}

function walk(element) {
  return [element, ...element.children.flatMap(walk)];
}

test('signed-out history is private and does not contact the API', async () => {
  const page = makePage({ authenticated: false });
  await page.settle();
  assert.equal(page.requests.length, 0);
  assert.equal(page.elements.get('library-list').hidden, true);
  assert.equal(page.elements.get('library-sign-in').hidden, false);
  assert.match(page.elements.get('library-notice').textContent, /Sign in with Google/);
});

test('history sends Cognito access token and safely renders filename as text', async () => {
  const page = makePage({ responses: [{ payload: { jobs: [{
    job_id: JOB_A, status: 'succeeded', filename: '<img src=x onerror=alert(1)>.mp4',
    report_available: true, duration_seconds: 12.8, created_at: 1795046400,
    completed_at: 1795046700, analysis_wall_ms: 170_000,
    report_expires_at: 1795305600
  }], next_cursor: null } }] });
  await page.settle();
  assert.equal(page.requests.length, 1);
  const request = page.requests[0];
  assert.equal(new URL(request.url).pathname, '/analysis/jobs');
  assert.equal(new URL(request.url).searchParams.get('limit'), '20');
  assert.equal(new URL(request.url).searchParams.has('user_id'), false);
  assert.equal(request.options.headers.Authorization, 'Bearer private-access-token');
  assert.equal(request.options.credentials, 'omit');
  const card = page.elements.get('library-list').children[0];
  const nodes = walk(card);
  assert.equal(nodes.find(item => item.tagName === 'h3').textContent, '<img src=x onerror=alert(1)>.mp4');
  assert.equal(nodes.find(item => item.tagName === 'a').href, '/demos/?job=' + JOB_A);
  assert.match(card.textContent, /Clip length12\.8|Clip length13 sec/);
  assert.equal(page.elements.get('library-list').hidden, false);
});

test('opaque pagination uses cursor unchanged and avoids duplicate jobs', async () => {
  const cursor = 'Y3Vyc29yLXVudHJ1c3RlZD8vK3wv';
  const page = makePage({ responses: [
    { payload: { jobs: [{ job_id: JOB_A, status: 'running' }], next_cursor: cursor } },
    { payload: { jobs: [{ job_id: JOB_A, status: 'running' }, { job_id: JOB_B,
      status: 'failed' }], next_cursor: null } }
  ] });
  await page.settle();
  assert.equal(page.elements.get('library-more').hidden, false);
  page.elements.get('library-more').click();
  await page.settle();
  assert.equal(new URL(page.requests[1].url).searchParams.get('cursor'), cursor);
  assert.equal(page.elements.get('library-list').children.length, 2);
  assert.equal(page.elements.get('library-more').hidden, true);
});

test('missing history endpoint gives a rollout message without retrying', async () => {
  const page = makePage({ responses: [{ status: 404 }] });
  await page.settle();
  assert.match(page.elements.get('library-notice').textContent, /being rolled out/);
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements.get('library-more').hidden, true);
});

test('expired sign-in receives 401 and stops exposing previous history', async () => {
  const page = makePage({ responses: [{ status: 401 }] });
  await page.settle();
  assert.equal(page.elements.get('library-list').hidden, true);
  assert.equal(page.elements.get('library-sign-in').hidden, false);
  assert.equal(page.storage.has('strokesense-aws-dev-auth'), false);
});

test('owner can revoke staff review consent, with no optimistic state change', async () => {
  const page = makePage({ responses: [
    { payload: { jobs: [{ job_id: JOB_A, filename: 'practice.mp4',
      status: 'succeeded', report_available: true, allow_admin_review: true }], next_cursor: null } },
    { status: 200, payload: { allow_admin_review: false } }
  ] });
  await page.settle();
  const card = page.elements.get('library-list').children[0];
  const button = walk(card).find(item => item.tagName === 'button' && item.textContent === 'Revoke staff access');
  assert.equal(button.textContent, 'Revoke staff access');
  assert.equal(button.hidden, false);
  button.click();
  await page.settle();
  assert.equal(page.requests.length, 2);
  assert.equal(new URL(page.requests[1].url).pathname, '/analysis/jobs/' + JOB_A + '/review');
  assert.equal(page.requests[1].options.method, 'POST');
  assert.equal(page.requests[1].options.headers.Authorization, 'Bearer private-access-token');
  assert.deepEqual(JSON.parse(page.requests[1].options.body), { allow_admin_review: false });
  assert.equal(button.hidden, true);
  assert.match(card.textContent, /Staff review access revoked/);
});

test('owner can watch annotated video with private temporary same-bucket S3 link', async () => {
  const url = 'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/reports/free/example/annotated.mp4?X-Amz-Signature=private';
  const page = makePage({ responses: [
    { payload: { jobs: [{ job_id: JOB_A, filename: 'practice.mp4', status: 'succeeded',
      report_available: true }], next_cursor: null } },
    { payload: { job_id: JOB_A, video_url: url, expires_in: 50 } }
  ] });
  await page.settle();
  const buttons = walk(page.elements.get('library-list').children[0]);
  buttons.find(item => item.tagName === 'button' && item.textContent === 'Watch annotated video').click();
  await page.settle();
  assert.equal(new URL(page.requests[1].url).pathname, '/reports/' + JOB_A + '/artifacts');
  assert.equal(page.requests[1].options.headers.Authorization, 'Bearer private-access-token');
  assert.equal(page.elements.get('library-video-player').src, url);
  assert.equal(page.elements.get('library-video-panel').hidden, false);
  assert.doesNotMatch(page.elements.get('library-video-notice').textContent, /X-Amz-Signature/);
  page.elements.get('library-close-video').click();
  assert.equal(page.elements.get('library-video-player').src, '');
});

test('missing annotated artifact never falls back to raw footage', async () => {
  const page = makePage({ responses: [
    { payload: { jobs: [{ job_id: JOB_A, status: 'succeeded', report_available: true }], next_cursor: null } },
    { payload: { job_id: JOB_A, video_url: null } }
  ] });
  await page.settle();
  walk(page.elements.get('library-list').children[0])
    .find(item => item.tagName === 'button' && item.textContent === 'Watch annotated video').click();
  await page.settle();
  assert.equal(page.elements.get('library-video-player').src, '');
  assert.match(page.elements.get('library-notice').textContent, /No annotated video was saved/);
});

test('history route is included in build and navigation', () => {
  const build = readFileSync(new URL('../build.mjs', import.meta.url), 'utf8');
  const homepage = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const history = readFileSync(new URL('../library/index.html', import.meta.url), 'utf8');
  assert.match(build, /'library'/);
  assert.match(homepage, /href="\/library\/"/);
  assert.match(history, /name="robots" content="noindex, nofollow"/);
  assert.match(history, /referrerpolicy="no-referrer"/);
  assert.doesNotMatch(source, /\.innerHTML\s*=/);
});
