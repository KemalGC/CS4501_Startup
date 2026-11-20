import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/recent-analyses.js', import.meta.url), 'utf8');
const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const pageHtml = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');
const JOB = 'e'.repeat(32);
const apiBase = 'https://example.execute-api.us-east-1.amazonaws.com';
const privateUrl = 'https://strokesense-aws-dev-851226124502-us-east-1.s3.us-east-1.amazonaws.com/reports/free/test/report.json?X-Amz-Signature=private';

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.dataset = {};
    this.hidden = false;
    this.open = false;
    this.disabled = false;
    this._text = '';
    this.srcdoc = '';
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = [...children]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); if (name === 'srcdoc') this.srcdoc = ''; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  dispatch(name) { this.listeners.get(name)?.(); }
  set innerHTML(_value) { throw Error('Untrusted report HTML must never enter the main DOM.'); }
}

function page({ signedIn = true, responses = [] } = {}) {
  const storage = new Map();
  if (signedIn) storage.set('strokesense-aws-dev-auth', JSON.stringify({
    accessToken: 'private-token', expiresAt: Date.now() + 500_000
  }));
  const elements = new Map([
    ['recent-analyses-list', new FakeElement()],
    ['recent-analyses-notice', new FakeElement()],
    ['recent-analyses-refresh', new FakeElement('button')]
  ]);
  const requests = [];
  const globalWindow = { STROKESENSE_AWS_CONFIG: { apiBaseUrl: apiBase } };
  runInNewContext(source, {
    window: globalWindow,
    document: {
      getElementById: id => elements.get(id) || null,
      createElement: tag => new FakeElement(tag)
    },
    sessionStorage: { getItem: key => storage.get(key) ?? null },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      const next = responses.shift();
      if (!next) throw Error('Unexpected request to ' + url);
      return {
        ok: (next.status || 200) < 400, status: next.status || 200,
        headers: { get() { return null; } },
        json: async () => next.body
      };
    },
    URL, Date, AbortController, Promise,
    setTimeout: () => 1,
    clearTimeout() {}
  });
  return {
    elements, requests, window: globalWindow,
    async settle() { await new Promise(resolve => setImmediate(resolve)); }
  };
}

const walk = root => [root, ...root.children.flatMap(walk)];

test('analyzer has an accessible expandable owner-only previous analyses section', () => {
  assert.match(pageHtml, /id="recent-analyses-list"/);
  assert.match(pageHtml, /src="\/assets\/recent-analyses\.js"/);
  assert.match(client, /StrokeSenseRecentAnalyses\?\.notifySubmitted\(upload\.video_id, chosenName, 'uploading'\)/);
  assert.match(client, /StrokeSenseRecentAnalyses\?\.notifySubmitted\(job\.job_id, chosenName\)/);
  assert.match(client, /StrokeSenseRecentAnalyses\?\.notifyCompleted\(jobId\)/);
  assert.match(client, /finishSignIn\(\)\.then\(\(\) => \{[\s\S]*?StrokeSenseRecentAnalyses\?\.refresh\(\)/);
  assert.doesNotMatch(source, /\.innerHTML\s*=/);
});

test('signed-out user never fetches other people\'s analysis history', async () => {
  const browser = page({ signedIn: false });
  await browser.settle();
  assert.equal(browser.requests.length, 0);
  assert.equal(browser.elements.get('recent-analyses-list').hidden, true);
});

test('previous report expands into a validated owner-authorized sandboxed iframe', async () => {
  const browser = page({ responses: [
    { body: { jobs: [{
      job_id: JOB, filename: '<svg onload=alert(1)>rowing.mp4', status: 'succeeded',
      report_available: true, created_at: 1795046400
    }], next_cursor: null } },
    { body: { download_url: privateUrl } },
    { body: { schema_version: 'strokesense-free-report-v1', job_id: JOB,
      report_html: '<html><body>Private coaching report</body></html>' } }
  ] });
  await browser.settle();
  assert.equal(browser.requests.length, 1);
  assert.equal(new URL(browser.requests[0].url).pathname, '/analysis/jobs');
  assert.equal(browser.requests[0].options.headers.Authorization, 'Bearer private-token');
  assert.equal(browser.requests[0].options.credentials, 'omit');
  const details = browser.elements.get('recent-analyses-list').children[0];
  assert.equal(details.tagName, 'details');
  assert.match(details.textContent, /<svg onload=alert\(1\)>rowing\.mp4/);
  const anchorUrls = walk(details).filter(node => node.tagName === 'a').map(node => node.href);
  assert.ok(anchorUrls.includes('/demos/?job=' + JOB));
  assert.ok(anchorUrls.includes('/library/?video=' + JOB));
  const frame = walk(details).find(node => node.tagName === 'iframe');
  assert.equal(frame.attributes.get('sandbox'), 'allow-same-origin');
  assert.equal(frame.hidden, true);
  details.open = true;
  details.dispatch('toggle');
  await browser.settle();
  assert.equal(browser.requests.length, 3);
  assert.equal(new URL(browser.requests[1].url).pathname, '/reports/' + JOB);
  assert.equal(browser.requests[1].options.headers.Authorization, 'Bearer private-token');
  assert.equal(browser.requests[2].url, privateUrl);
  assert.equal(browser.requests[2].options.credentials, 'omit');
  assert.match(frame.srcdoc, /Private coaching report/);
  assert.equal(frame.hidden, false);
  details.open = false;
  details.dispatch('toggle');
  assert.equal(frame.srcdoc, '');
  assert.equal(frame.hidden, true);
});

test('uploaded and completed jobs appear immediately even before history index catches up', async () => {
  const browser = page({ responses: [
    { body: { jobs: [], next_cursor: null } },
    { body: { jobs: [], next_cursor: null } },
    { body: { jobs: [], next_cursor: null } }
  ] });
  await browser.settle();
  browser.window.StrokeSenseRecentAnalyses.notifySubmitted(JOB, 'morning-eight.mp4', 'uploading');
  let card = browser.elements.get('recent-analyses-list').children[0];
  assert.match(card.textContent, /morning-eight\.mp4/);
  assert.match(card.textContent, /Processing/);
  await browser.settle();
  browser.window.StrokeSenseRecentAnalyses.notifyCompleted(JOB);
  card = browser.elements.get('recent-analyses-list').children[0];
  assert.match(card.textContent, /Report ready/);
  const links = walk(card).filter(node => node.tagName === 'a').map(node => node.href);
  assert.ok(links.includes('/library/?video=' + JOB));
  await browser.settle();
  assert.equal(browser.requests.length, 3);
});

test('expired analysis is still listed but cannot open expired media', async () => {
  const browser = page({ responses: [
    { body: { jobs: [{ job_id: JOB, filename: 'old.mp4', status: 'succeeded',
      report_available: false, created_at: 1795046400 }], next_cursor: null } }
  ] });
  await browser.settle();
  const card = browser.elements.get('recent-analyses-list').children[0];
  assert.match(card.textContent, /Report expired/);
  assert.equal(walk(card).filter(node => node.tagName === 'iframe').length, 0);
  assert.equal(walk(card).filter(node => node.tagName === 'a').length, 0);
});
