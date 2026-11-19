import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/admin.js', import.meta.url), 'utf8');
const JOB_ID = '8d323d41ed3a4ffcaee778201670098e';
const VIDEO_URL = 'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/reports/test/video.mp4?X-Amz-Signature=sensitive';

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this._text = '';
    this.children = [];
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.src = '';
  }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(_value) { throw Error('Sensitive admin fields must never be interpreted as HTML.'); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this._text = ''; this.children = [...children]; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  click() { this.listeners.get('click')?.(); }
  removeAttribute(name) { if (name === 'src') this.src = ''; }
  pause() {}
  load() {}
}

function browser({ authenticated = true, responses = [] } = {}) {
  const ids = [
    'admin-account', 'admin-sign-in', 'admin-refresh', 'admin-notice',
    'admin-list', 'admin-more', 'admin-video-panel', 'admin-video-player',
    'admin-video-title', 'admin-video-notice', 'admin-close-video', 'admin-refresh-video'
  ];
  const elements = new Map(ids.map(id => [id, new FakeElement()]));
  const storage = new Map();
  const requests = [];
  for (const id of ['admin-sign-in', 'admin-refresh', 'admin-list', 'admin-more', 'admin-video-panel']) {
    elements.get(id).hidden = true;
  }
  if (authenticated) storage.set('strokesense-aws-dev-auth', JSON.stringify({
    accessToken: 'privileged-test-access', expiresAt: Date.now() + 3_600_000
  }));
  runInNewContext(source, {
    window: { STROKESENSE_AWS_CONFIG: { apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com' } },
    document: {
      getElementById: id => elements.get(id),
      createElement: tag => new FakeElement(tag)
    },
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      removeItem: key => storage.delete(key)
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const response = responses.shift();
      if (!response) throw Error('Unexpected extra request');
      return { status: response.status || 200, ok: (response.status || 200) < 400,
        json: async () => response.payload };
    },
    URL, AbortController, setTimeout, clearTimeout
  });
  return { elements, requests, storage,
    async settle() { await new Promise(resolve => setImmediate(resolve)); }
  };
}

function walk(element) { return [element, ...element.children.flatMap(walk)]; }

function optedInJob(overrides = {}) {
  return { job_id: JOB_ID, allow_admin_review: true, status: 'succeeded',
    filename: '<img src=x onerror=alert(1)>.mp4', video_available: true,
    analysis_wall_ms: 180_000, queue_wait_ms: 15_000,
    duration_seconds: 12.8, created_at: 1795046400, ...overrides };
}

test('admin page does not fetch data without an authenticated account', async () => {
  const page = browser({ authenticated: false });
  await page.settle();
  assert.equal(page.requests.length, 0);
  assert.equal(page.elements.get('admin-list').hidden, true);
  assert.equal(page.elements.get('admin-sign-in').hidden, false);
});

test('backend 403 keeps admin records private and never retries automatically', async () => {
  const page = browser({ responses: [{ status: 403 }] });
  await page.settle();
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements.get('admin-list').hidden, true);
  assert.equal(page.elements.get('admin-video-panel').hidden, true);
  assert.equal(page.elements.get('admin-refresh').hidden, true);
  assert.match(page.elements.get('admin-notice').textContent, /does not have permission/);
});

test('missing staff API shows a one-time rollout error without polling', async () => {
  const page = browser({ responses: [{ status: 404 }] });
  await page.settle();
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements.get('admin-list').hidden, true);
  assert.match(page.elements.get('admin-notice').textContent, /not yet available/);
});

test('only opted-in records render with analysis timing and no owner identifiers', async () => {
  const page = browser({ responses: [{ payload: { jobs: [
    optedInJob(), optedInJob({ job_id: '87ffb753de784010900883b013649be1', allow_admin_review: false })
  ], next_cursor: null } }] });
  await page.settle();
  const cards = page.elements.get('admin-list').children;
  assert.equal(cards.length, 1);
  const nodes = walk(cards[0]);
  assert.equal(nodes.find(element => element.tagName === 'h3').textContent, '<img src=x onerror=alert(1)>.mp4');
  assert.match(cards[0].textContent, /Analysis wall time3:00/);
  assert.match(cards[0].textContent, /Queue wait15 sec/);
  assert.equal(page.requests[0].options.headers.Authorization, 'Bearer privileged-test-access');
  assert.equal(new URL(page.requests[0].url).pathname, '/admin/jobs');
  assert.equal(new URL(page.requests[0].url).searchParams.get('limit'), '20');
  assert.equal(new URL(page.requests[0].url).searchParams.has('owner'), false);
});

test('video is requested only when clicked, with consent rechecked server-side', async () => {
  const page = browser({ responses: [
    { payload: { jobs: [optedInJob()], next_cursor: null } },
    { payload: { job_id: JOB_ID, video_url: VIDEO_URL, video_type: 'annotated', expires_in: 60 } }
  ] });
  await page.settle();
  assert.equal(page.requests.length, 1);
  const card = page.elements.get('admin-list').children[0];
  walk(card).find(element => element.tagName === 'button').click();
  await page.settle();
  assert.equal(page.requests.length, 2);
  assert.equal(new URL(page.requests[1].url).pathname, '/admin/videos/' + JOB_ID);
  assert.equal(page.requests[1].options.headers.Authorization, 'Bearer privileged-test-access');
  assert.equal(page.elements.get('admin-video-player').src, VIDEO_URL);
  assert.equal(page.elements.get('admin-video-panel').hidden, false);
  assert.match(page.elements.get('admin-video-notice').textContent, /Annotated analysis/);
  assert.doesNotMatch(page.elements.get('admin-video-notice').textContent, /X-Amz-Signature/);
  page.elements.get('admin-close-video').click();
  assert.equal(page.elements.get('admin-video-player').src, '');
  assert.equal(page.elements.get('admin-video-panel').hidden, true);
});

test('admin review pagination preserves opaque cursor and deduplicates jobs', async () => {
  const cursor = 'TmV4dC9jdXJzb3I/Kys=';
  const page = browser({ responses: [
    { payload: { jobs: [optedInJob()], next_cursor: cursor } },
    { payload: { jobs: [optedInJob(), optedInJob({ job_id: '87ffb753de784010900883b013649be1' })], next_cursor: null } }
  ] });
  await page.settle();
  assert.equal(page.elements.get('admin-more').hidden, false);
  page.elements.get('admin-more').click();
  await page.settle();
  assert.equal(new URL(page.requests[1].url).searchParams.get('cursor'), cursor);
  assert.equal(page.elements.get('admin-list').children.length, 2);
  assert.equal(page.elements.get('admin-more').hidden, true);
});

test('admin rejects a non-S3 video URL rather than rendering it', async () => {
  const page = browser({ responses: [
    { payload: { jobs: [optedInJob()], next_cursor: null } },
    { payload: { job_id: JOB_ID, video_url: 'https://unsafe.example/video.mp4' } }
  ] });
  await page.settle();
  walk(page.elements.get('admin-list').children[0]).find(element => element.tagName === 'button').click();
  await page.settle();
  assert.equal(page.elements.get('admin-video-player').src, '');
  assert.match(page.elements.get('admin-notice').textContent, /Unable to open video/);
});

test('staff video URL must use this site\'s bucket and be presigned without credentials or fragments', async () => {
  const disallowed = [
    'https://other-bucket.s3.us-east-1.amazonaws.com/video.mp4?X-Amz-Signature=test',
    'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/video.mp4',
    'https://user:password@strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/video.mp4?X-Amz-Signature=test',
    'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/video.mp4?X-Amz-Signature=test#fragment'
  ];
  for (const video_url of disallowed) {
    const page = browser({ responses: [
      { payload: { jobs: [optedInJob()], next_cursor: null } },
      { payload: { job_id: JOB_ID, video_url } }
    ] });
    await page.settle();
    walk(page.elements.get('admin-list').children[0]).find(element => element.tagName === 'button').click();
    await page.settle();
    assert.equal(page.elements.get('admin-video-player').src, '');
    assert.match(page.elements.get('admin-notice').textContent, /invalid secure video URL/);
  }
});

test('unlinked admin route ships but never appears in public navigation', () => {
  const html = readFileSync(new URL('../admin/index.html', import.meta.url), 'utf8');
  const homepage = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const library = readFileSync(new URL('../library/index.html', import.meta.url), 'utf8');
  const build = readFileSync(new URL('../build.mjs', import.meta.url), 'utf8');
  assert.match(html, /noindex, nofollow/);
  assert.match(build, /'admin'/);
  assert.doesNotMatch(homepage, /href="\/admin\//);
  assert.doesNotMatch(library, /href="\/admin\//);
  assert.doesNotMatch(source, /\.innerHTML\s*=/);
});
