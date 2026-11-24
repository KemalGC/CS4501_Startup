import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const AUTH = 'strokesense-aws-dev-auth';
const API = 'https://example.execute-api.us-east-1.amazonaws.com';

function response(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function browser({ signedIn = true, frontendEnabled = true, responses = [] } = {}) {
  const elements = new Map();
  const requests = [];
  const storage = new Map();
  if (signedIn) storage.set(AUTH, JSON.stringify({ accessToken: 'account-token', expiresAt: Date.now() + 600000 }));
  class Element {
    constructor(id) {
      this.id = id; this.checked = id === 'tier-free'; this.hidden = false;
      this.disabled = false; this.textContent = ''; this.dataset = {}; this.listeners = new Map();
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    addEventListener(name, action) { this.listeners.set(name, action); }
    removeAttribute() {}
    setAttribute() {}
    set innerHTML(_) { throw Error('Account data must not be interpreted as markup.'); }
    dispatch(name) { return this.listeners.get(name)?.(); }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  class LocalURL extends URL {}
  LocalURL.createObjectURL = () => 'blob:local-video';
  LocalURL.revokeObjectURL = () => {};
  runInNewContext(source, {
    window: {
      STROKESENSE_AWS_CONFIG: {
        apiBaseUrl: API, cognitoDomain: 'https://example.auth.us-east-1.amazoncognito.com',
        cognitoClientId: 'client', cpuAnalysisEnabled: true, premiumAnalysisEnabled: frontendEnabled
      }, location: { origin: 'https://strokesense-aws-dev.vercel.app', search: '', hash: '' }
    },
    document: { getElementById: element, querySelectorAll: () => [] },
    sessionStorage: {
      getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const next = responses.shift();
      if (!next) throw Error('Unexpected network request');
      return typeof next === 'function' ? next(url, options) : next;
    },
    URL: LocalURL, URLSearchParams, AbortController, Blob, setTimeout, clearTimeout
  });
  return { elements, requests, storage,
    async settle() { await new Promise(resolve => setImmediate(resolve)); },
    selectFile() {
      const file = new Blob(['rowing'], { type: 'video/mp4' });
      Object.defineProperty(file, 'name', { value: 'rowing.mp4' });
      element('video-upload').files = [file];
      element('video-upload').dispatch('change');
    },
    selectPremium() {
      element('tier-free').checked = false;
      element('tier-paid').checked = true;
      element('tier-paid').dispatch('change');
    }
  };
}

const account = (granted, available, is_admin = false) => response({ is_admin, premium_access: { granted, available } });

test('signed-out visitors cannot enable Premium or see admin actions', async () => {
  const page = browser({ signedIn: false });
  await page.settle();
  page.selectFile();
  assert.equal(page.requests.length, 0);
  assert.equal(page.elements.get('tier-paid').disabled, true);
  assert.equal(page.elements.get('admin-console-link').hidden, true);
  assert.equal(page.elements.get('run-analysis').disabled, true);
});

test('a server-denied account retains Free Analysis and cannot bypass Premium using a radio change', async () => {
  const page = browser({ responses: [account(false, false)] });
  await page.settle();
  page.selectFile();
  assert.equal(page.elements.get('run-analysis').disabled, false);
  assert.match(page.elements.get('premium-access-status').textContent, /not been granted/);
  page.selectPremium();
  assert.equal(page.elements.get('tier-free').checked, true);
  // Bypass the disabled radio in the test to exercise the actual submit guard.
  page.elements.get('tier-paid').checked = true;
  page.elements.get('tier-free').checked = false;
  await page.elements.get('run-analysis').dispatch('click');
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, API + '/me');
  assert.equal(page.requests[0].options.headers.Authorization, 'Bearer account-token');
});

test('a Premium grant does not advertise or start unavailable GPU processing', async () => {
  const page = browser({ responses: [account(true, false, true)] });
  await page.settle();
  page.selectFile();
  assert.equal(page.elements.get('premium-access-status').textContent, 'Premium access granted');
  assert.match(page.elements.get('premium-runtime-status').textContent, /not available yet/);
  assert.equal(page.elements.get('tier-paid').disabled, true);
  assert.equal(page.elements.get('admin-console-link').hidden, false);
  assert.equal(page.elements.get('run-analysis').disabled, false, 'Free CPU remains usable');
});

test('the frontend rollout flag cannot bypass server permission or availability', async () => {
  const page = browser({ frontendEnabled: false, responses: [account(true, true)] });
  await page.settle();
  assert.equal(page.elements.get('tier-paid').disabled, true);
  assert.match(page.elements.get('premium-runtime-status').textContent, /not available yet/);
});

test('Premium requires all gates and preserves the deployed tier wire format', async () => {
  const page = browser({ responses: [account(true, true), response({ error: { message: 'Upload intentionally not started.' } }, 503)] });
  await page.settle();
  page.selectFile();
  page.selectPremium();
  assert.equal(page.elements.get('tier-paid').disabled, false);
  assert.equal(page.elements.get('run-analysis').textContent, 'Start Premium Analysis');
  await page.elements.get('run-analysis').dispatch('click');
  const upload = page.requests.find(item => item.url === API + '/uploads/start');
  assert.ok(upload);
  assert.equal(JSON.parse(upload.options.body).tier, 'paid');
});

test('missing or malformed capability responses fail closed without blocking the Free CPU option', async () => {
  for (const reply of [response({}, 404), response({ is_admin: true, premium_access: { granted: 'true', available: true } })]) {
    const page = browser({ responses: [reply] });
    await page.settle();
    page.selectFile();
    assert.equal(page.elements.get('tier-paid').disabled, true);
    assert.equal(page.elements.get('admin-console-link').hidden, true);
    assert.equal(page.elements.get('run-analysis').disabled, false);
    assert.match(page.elements.get('premium-access-status').textContent, /could not be checked/);
  }
});

test('refreshing revoked access clears Premium selection and admin controls', async () => {
  const page = browser({ responses: [account(true, true, true), account(false, false, false)] });
  await page.settle();
  page.selectPremium();
  await page.elements.get('premium-refresh').dispatch('click');
  assert.equal(page.elements.get('tier-free').checked, true);
  assert.equal(page.elements.get('tier-paid').disabled, true);
  assert.equal(page.elements.get('admin-console-link').hidden, true);
});

test('a late account response cannot restore permissions after sign-out', async () => {
  let finish;
  const page = browser({ responses: [() => new Promise(resolve => { finish = resolve; })] });
  await page.settle();
  page.elements.get('google-logout').dispatch('click');
  finish(account(true, true, true));
  await page.settle();
  assert.equal(page.storage.has(AUTH), false);
  assert.equal(page.elements.get('admin-console-link').hidden, true);
  assert.equal(page.elements.get('tier-paid').disabled, true);
  assert.match(page.elements.get('premium-access-status').textContent, /Sign in/);
});

test('an expired server session clears local account authorization', async () => {
  const page = browser({ responses: [response({}, 401)] });
  await page.settle();
  assert.equal(page.storage.has(AUTH), false);
  assert.equal(page.elements.get('google-login').hidden, false);
  assert.equal(page.elements.get('admin-console-link').hidden, true);
});
