import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const dashboard = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');

test('progress panel separates uploading, AWS processing, and report readiness', () => {
  for (const id of ['analysis-stage-upload', 'analysis-stage-analysis', 'analysis-stage-report']) {
    assert.match(dashboard, new RegExp(`id="${id}"`));
  }
  assert.doesNotMatch(client, /Math\.max\(90, Math\.min\(99/);

  const snapshots = [];
  const elements = new Map();
  const handlers = new Map();
  class Element {
    constructor(id) {
      this.id = id;
      this._textContent = '';
      this._value = 0;
      this.hidden = false;
      this.disabled = false;
      this.dataset = {};
      this.attributes = new Map();
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    get value() { return this._value; }
    set value(value) { this._value = value; this.attributes.set('value', String(value)); }
    get textContent() { return this._textContent; }
    set textContent(value) {
      this._textContent = String(value);
      if (this.id === 'analysis-detail') {
        snapshots.push({
          label: elements.get('analysis-status').textContent,
          percentage: elements.get('analysis-percentage').textContent,
          detail: this._textContent,
          indeterminate: !elements.get('analysis-progress-bar').attributes.has('value')
        });
      }
    }
    addEventListener(name, callback) { handlers.set(`${this.id}:${name}`, callback); }
    removeAttribute(name) { this.attributes.delete(name); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    click() {}
    get checked() { return this.id === 'tier-free'; }
  }
  function element(id) {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  }
  const sessionData = new Map([
    ['strokesense-aws-dev-auth', JSON.stringify({ accessToken: 'test-token', expiresAt: Date.now() + 600_000 })]
  ]);
  const jobId = 'a'.repeat(32);
  const partSize = 5 * 1024 * 1024;
  const stages = ['runnable', 'starting', 'running', 'succeeded'];
  let stageIndex = 0;
  const response = payload => ({ ok: true, status: 200, json: async () => payload,
    headers: { get(name) { return name === 'ETag' ? '"etag"' : null; } } });
  const fakeFetch = async (url, options = {}) => {
    if (url.includes('/uploads/start')) return response({ video_id: jobId, part_size_bytes: partSize, part_count: 2 });
    if (url.includes('/uploads/part')) return response({ url: `https://private.s3.amazonaws.com/part` });
    if (url.includes('/uploads/complete')) return response({});
    if (url.endsWith('/analysis/jobs') && options.method === 'POST') return response({ job_id: jobId });
    if (url.includes('/analysis/jobs/')) return response({ status: stages[stageIndex++] || 'succeeded' });
    if (url.includes('/reports/')) return response({ download_url: 'https://private.s3.amazonaws.com/report.json' });
    if (url.endsWith('/report.json')) return response({ schema_version: 'strokesense-free-report-v1',
      job_id: jobId, report_html: '<html><body>OK</body></html>' });
    return response({});
  };
  class SafeURL extends URL {}
  SafeURL.createObjectURL = () => 'blob:test';
  SafeURL.revokeObjectURL = () => {};

  runInNewContext(client, {
    window: { STROKESENSE_AWS_CONFIG: {
      apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com',
      cognitoDomain: 'https://example.auth.us-east-1.amazoncognito.com',
      cognitoClientId: 'test', cpuAnalysisEnabled: true, deepAnalysisEnabled: false
    }, location: { origin: 'https://strokesense-aws-dev.vercel.app', search: '', hash: '' } },
    document: { getElementById: element, querySelectorAll: () => [] },
    sessionStorage: { getItem: key => sessionData.get(key) || null,
      setItem: (key, value) => sessionData.set(key, value), removeItem: key => sessionData.delete(key) },
    URL: SafeURL,
    URLSearchParams,
    fetch: fakeFetch,
    AbortController,
    Blob,
    Date,
    Promise,
    setTimeout: resolve => { resolve(); return 0; },
    clearTimeout() {}
  });

  const video = new Blob([new Uint8Array(partSize + 1234)], { type: 'video/mp4' });
  Object.defineProperty(video, 'name', { value: 'rowing.mp4' });
  element('video-upload').files = [video];
  handlers.get('video-upload:change')();
  assert.match(element('upload-feedback').textContent, /Local file check passed/);
  return handlers.get('run-analysis:click')().then(() => {
    const uploaded = snapshots.filter(item => item.label === 'Uploading to private storage');
    assert.equal(uploaded.at(-1).percentage, '100%');
    assert.match(uploaded.at(-1).detail, /2 of 2 parts uploaded/);
    for (const state of ['Queued for processing', 'Starting AWS worker', 'Processing video on AWS']) {
      const item = snapshots.find(snapshot => snapshot.label === state);
      assert.ok(item, `missing stage: ${state}`);
      assert.equal(item.percentage, 'Working…');
      assert.equal(item.indeterminate, true);
    }
    assert.equal(snapshots.at(-1).label, 'Report ready');
    assert.equal(snapshots.at(-1).percentage, '100%');
    assert.doesNotMatch(element('upload-feedback').textContent, /No video has been uploaded/);
  });
});
