import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const page = readFileSync(new URL('../library/index.html', import.meta.url), 'utf8');
const owner = readFileSync(new URL('../assets/library.js', import.meta.url), 'utf8');
const publicFeed = readFileSync(new URL('../assets/community-feed.js', import.meta.url), 'utf8');
const api = readFileSync(new URL('../../strokesense/aws_app/handler.py', import.meta.url), 'utf8');

test('library keeps private and public community videos in separate accessible tabs', () => {
  for (const id of ['library-tab-private', 'library-tab-community', 'library-private-section',
    'library-community-section', 'community-list', 'community-video-player']) {
    assert.match(page, new RegExp('id="' + id + '"'));
  }
  assert.match(page, /id="library-community-section"[^>]+hidden/);
  assert.match(page, /src="\/assets\/community-feed\.js"/);
  assert.match(page, /Shared by their owners/);
});

test('owner public sharing is opt in and independent from admin review consent', () => {
  assert.match(owner, /\/analysis\/jobs\/' \+ encodeURIComponent\(job\.job_id\) \+ '\/publish'/);
  assert.match(owner, /window\.confirm/);
  assert.match(owner, /public: next/);
  assert.match(owner, /job\.community_shared === true/);
  assert.match(owner, /allow_admin_review/);
  assert.match(owner, /Unpublish video/);
});

test('anonymous community browsing never uses browser auth token or raw user identifiers', () => {
  assert.match(publicFeed, /\/community\/videos/);
  assert.match(publicFeed, /credentials: 'omit'/);
  assert.doesNotMatch(publicFeed, /sessionStorage|Authorization:|accessToken|\.innerHTML\s*=/);
  assert.doesNotMatch(publicFeed, /video\.filename|video\.user_id|report_html/);
  assert.match(publicFeed, /X-Amz-Signature/);
  assert.match(publicFeed, /community-video-player/);
});

test('public APIs remain explicit separate routes before the Cognito requirement', () => {
  const list = api.indexOf('if method == "GET" and path == "/community/videos"');
  const auth = api.indexOf('user_id = _user_id(event)');
  const publish = api.indexOf('COMMUNITY_PUBLISH_ROUTE.fullmatch(path)');
  assert.ok(list > 0 && list < auth && publish > auth);
});


test('anonymous visitor can browse and play only the opt-in annotated clip', async () => {
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag;
      this.children = [];
      this.listeners = {};
      this.hidden = false;
      this.disabled = false;
      this.dataset = {};
      this.textContent = '';
      this.src = '';
      this.href = '';
      this.classList = { toggle() {} };
    }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...items) { this.children = items; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { this.listeners.click?.(); }
    removeAttribute(name) { if (name === 'src' || name === 'href') this[name] = ''; }
    setAttribute(name, value) { this[name] = value; }
    pause() {}
    load() {}
  }
  const ids = ['library-private-section', 'library-community-section', 'library-tab-private',
    'library-tab-community', 'community-refresh', 'community-list', 'community-notice', 'community-more',
    'community-video-panel', 'community-video-player', 'community-video-link', 'community-close-video',
    'community-refresh-video', 'community-video-notice', 'community-video-title'];
  const elements = new Map(ids.map(id => [id, new Element()]));
  const id = 'a'.repeat(32);
  const videoUrl = 'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/reports/free/safe/annotated.mp4?X-Amz-Signature=test';
  const requests = [];
  runInNewContext(publicFeed, {
    window: {
      STROKESENSE_AWS_CONFIG: { apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com' },
      location: { hash: '#community' },
      history: { replaceState() {} }
    },
    document: {
      getElementById: key => elements.get(key) || null,
      createElement: tag => new Element(tag)
    },
    URL, AbortController, setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => {
      requests.push({ url: String(url), options });
      if (String(url).endsWith('/community/videos/' + id)) {
        return { ok: true, json: async () => ({ job_id: id, video_type: 'annotated', video_url: videoUrl, expires_in: 60 }) };
      }
      return { ok: true, json: async () => ({
        videos: [{ job_id: id, created_at: '2026-11-19T12:00:00Z', duration_seconds: 12.8 }],
        next_cursor: null
      }) };
    }
  });
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements.get('library-private-section').hidden, true);
  assert.equal(elements.get('library-community-section').hidden, false);
  assert.equal(elements.get('community-list').children.length, 1);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.credentials, 'omit');
  assert.equal(requests[0].options.headers, undefined, 'anonymous fetch must not include a private token');
  const card = elements.get('community-list').children[0];
  card.children.at(-1).click();
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 2);
  assert.equal(elements.get('community-video-player').src, videoUrl);
  assert.equal(elements.get('community-video-link').href, videoUrl);
  elements.get('library-tab-private').click();
  assert.equal(elements.get('community-video-player').src, '');
  assert.equal(elements.get('community-video-link').href, '');
  assert.equal(elements.get('library-community-section').hidden, true);
});
