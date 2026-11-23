import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const jobId = 'b'.repeat(32);
const apiBase = 'https://example.execute-api.us-east-1.amazonaws.com';
const reportUrl = 'https://private-bucket.s3.us-east-1.amazonaws.com/reports/test/report.json?X-Amz-Signature=test';
const authKey = 'strokesense-aws-dev-auth';
const jobKey = 'strokesense-aws-dev-active-job';

function loadPage(storage) {
  const elements = new Map();
  const handlers = new Map();
  const requests = [];
  let renderCount = 0;
  class Element {
    constructor(id) {
      this.id = id;
      this.hidden = true;
      this.disabled = false;
      this.textContent = '';
      this.dataset = {};
      this.checked = id === 'tier-free';
      this.clickCount = 0;
      this.attributes = new Map();
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    addEventListener(name, callback) { handlers.set(`${this.id}:${name}`, callback); }
    removeAttribute(name) { this.attributes.delete(name); }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    click() { this.clickCount += 1; }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const response = body => ({
    ok: true, status: 200,
    json: async () => body,
    headers: { get() { return null; } }
  });
  const fetch = async (url, options = {}) => {
    requests.push({ url, method: options.method || 'GET' });
    if (url === `${apiBase}/me`) return response({ is_admin: false, premium_access: { granted: false, available: false } });
    if (url === `${apiBase}/analysis/jobs/${jobId}`) return response({ job_id: jobId, status: 'succeeded' });
    if (url === `${apiBase}/reports/${jobId}`) return response({ download_url: reportUrl });
    if (url === `${apiBase}/reports/${jobId}/artifacts`) return response({ job_id: jobId, rowers: {} });
    if (url === reportUrl) return response({
      schema_version: 'strokesense-free-report-v1',
      job_id: jobId,
      report_html: '<html><body>Restored coaching report</body></html>'
    });
    throw Error(`Unexpected request: ${url}`);
  };
  class SafeURL extends URL {}
  SafeURL.createObjectURL = () => 'blob:restored-report';
  SafeURL.revokeObjectURL = () => {};
  runInNewContext(source, {
    window: {
      STROKESENSE_AWS_CONFIG: {
        apiBaseUrl: apiBase,
        cognitoDomain: 'https://example.auth.us-east-1.amazoncognito.com',
        cognitoClientId: 'test-client', cpuAnalysisEnabled: true, deepAnalysisEnabled: false
      },
      location: { origin: 'https://strokesense-aws-dev.vercel.app', search: '', hash: '' },
      StrokeSenseMediaViewer: {
        clear() {},
        render() { renderCount += 1; }
      }
    },
    document: { getElementById: element, querySelectorAll: () => [] },
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    URL: SafeURL, URLSearchParams, Blob, fetch, AbortController, Date, Promise, setTimeout, clearTimeout
  });
  return {
    elements, handlers, requests,
    get renderCount() { return renderCount; },
    async settle() { await new Promise(resolve => setImmediate(resolve)); }
  };
}

test('a completed private job restores on every refresh without resubmitting or redownloading', async () => {
  const storage = new Map([
    [authKey, JSON.stringify({ accessToken: 'owner-access-token', expiresAt: Date.now() + 600_000 })],
    [jobKey, jobId]
  ]);

  for (let refresh = 0; refresh < 2; refresh += 1) {
    const page = loadPage(storage);
    await page.settle();
    assert.equal(storage.get(jobKey), jobId, 'restoring a successful report must not forget the job');
    assert.equal(page.elements.get('analysis-result').hidden, false);
    assert.equal(page.elements.get('report-preview').hidden, false);
    assert.match(page.elements.get('report-frame').srcdoc, /Restored coaching report/);
    assert.equal(page.elements.get('download-report').clickCount, 0,
      'refresh must not trigger another automatic download');
    assert.equal(page.renderCount, 1, 'saved media must be rehydrated through owner-scoped routes');
    const reportRequests = page.requests.filter(request => request.url !== `${apiBase}/me`);
    assert.deepEqual(reportRequests.map(request => request.method), ['GET', 'GET', 'GET', 'GET']);
    assert.equal(reportRequests[0].url, `${apiBase}/analysis/jobs/${jobId}`);
  }

  const signedInPage = loadPage(storage);
  await signedInPage.settle();
  signedInPage.handlers.get('google-logout:click')();
  assert.equal(storage.has(jobKey), false, 'signing out must clear the saved job ID');
  assert.equal(storage.has(authKey), false, 'signing out must clear account tokens');
  assert.equal(signedInPage.elements.get('analysis-result').hidden, true);
});
