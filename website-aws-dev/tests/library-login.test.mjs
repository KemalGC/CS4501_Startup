import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const library = readFileSync(new URL('../assets/library.js', import.meta.url), 'utf8');
const libraryPage = readFileSync(new URL('../library/index.html', import.meta.url), 'utf8');
const AUTH_KEY = 'strokesense-aws-dev-auth';
const PKCE_KEY = 'strokesense-aws-dev-pkce';
const SITE = 'https://strokesense-aws-dev.vercel.app';
const COGNITO = 'https://strokesense-dev-851226124502.auth.us-east-1.amazoncognito.com';

function analyzer(storage, search, fetcher = async () => { throw Error('unexpected network call'); }) {
  const elements = new Map();
  const calls = { assigned: [], replaced: [], history: [], requests: [] };
  class Element {
    constructor(id) {
      this.id = id;
      this.dataset = {};
      this.checked = id === 'tier-free';
      this.hidden = false;
      this.disabled = false;
      this.textContent = '';
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    addEventListener() {}
    removeAttribute() {}
    setAttribute() {}
  }
  const dom = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const location = {
    origin: SITE, search, hash: '',
    assign(value) { calls.assigned.push(value); },
    replace(value) { calls.replaced.push(value); }
  };
  runInNewContext(client, {
    window: {
      STROKESENSE_AWS_CONFIG: {
        apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com',
        cognitoDomain: COGNITO, cognitoClientId: 'public-client-id',
        cpuAnalysisEnabled: true, deepAnalysisEnabled: false
      },
      location
    },
    document: { getElementById: dom, querySelectorAll: () => [] },
    history: { replaceState(_state, _unused, value) { calls.history.push(value); } },
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    crypto: webcrypto, TextEncoder, btoa, atob, URL, URLSearchParams, Date, Promise,
    fetch: async (url, options) => {
      calls.requests.push({ url, options });
      return fetcher(url, options);
    }
  });
  return { calls, elements, settle: () => new Promise(resolve => setImmediate(resolve)) };
}

test('Library sign-in starts OAuth automatically and returns to the Library after code exchange', async () => {
  assert.match(libraryPage, /id="library-sign-in" href="\/demos\/\?login=library"/);
  const storage = new Map();
  const first = analyzer(storage, '?login=library');
  // WebCrypto and OAuth PKCE preparation can finish after several turns
  // under loaded CI runners; observe the callback instead of assuming four.
  for (let i = 0; i < 100 && first.calls.assigned.length === 0; i++) {
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.deepEqual(first.calls.history, [SITE + '/demos/']);
  assert.equal(first.calls.assigned.length, 1, 'Library login must actually start Cognito, not just open the analyzer');
  const login = new URL(first.calls.assigned[0]);
  assert.equal(login.origin, COGNITO);
  assert.equal(login.searchParams.get('redirect_uri'), SITE + '/demos/');
  assert.equal(login.searchParams.get('identity_provider'), 'Google');
  const pending = JSON.parse(storage.get(PKCE_KEY));
  assert.equal(pending.returnTo, '/library/');
  assert.equal(pending.state, login.searchParams.get('state'));
  assert.equal(storage.has(AUTH_KEY), false);

  const callback = analyzer(storage, '?code=test-oauth-code&state=' + encodeURIComponent(pending.state),
    async (url, options) => {
      assert.equal(url, COGNITO + '/oauth2/token');
      const body = options.body;
      assert.equal(body.get('code_verifier'), pending.verifier);
      assert.equal(body.get('redirect_uri'), SITE + '/demos/');
      return { ok: true, status: 200, json: async () => ({
        access_token: 'owner-access-token', id_token: '', expires_in: 3600
      }) };
    });
  for (let i = 0; i < 4; i++) await callback.settle();
  assert.deepEqual(callback.calls.replaced, ['/library/']);
  assert.equal(callback.calls.requests.length, 1);
  assert.ok(JSON.parse(storage.get(AUTH_KEY)).expiresAt > Date.now());

  // A new Library page in the same tab sees the same account session.
  const ids = ['library-account', 'library-sign-in', 'library-refresh',
    'library-notice', 'library-list', 'library-more', 'library-video-panel',
    'library-video-player', 'library-video-title', 'library-video-notice',
    'library-close-video', 'library-refresh-video', 'library-video-link'];
  class LibraryElement {
    constructor() { this.hidden = true; this.disabled = false; this.dataset = {}; this.children = []; this.textContent = ''; }
    addEventListener() {}
    replaceChildren() { this.children = []; }
    pause() {}
    load() {}
    removeAttribute() {}
  }
  const elems = new Map(ids.map(id => [id, new LibraryElement()]));
  let calls = 0;
  runInNewContext(library, {
    window: { STROKESENSE_AWS_CONFIG: { apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com' }, location: { search: '' } },
    document: { getElementById: id => elems.get(id), createElement: () => new LibraryElement() },
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    fetch: async (url, options) => {
      calls++;
      assert.equal(new URL(url).pathname, '/analysis/jobs');
      assert.equal(options.headers.Authorization, 'Bearer owner-access-token');
      return { ok: true, status: 200, json: async () => ({ jobs: [], next_cursor: null }) };
    },
    URL, URLSearchParams, AbortController, setTimeout: () => 1, clearTimeout() {},
    Date, Promise
  });
  for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  assert.equal(elems.get('library-sign-in').hidden, true);
  assert.match(elems.get('library-account').textContent, /Signed in with Google/);
});

test('already signed-in visitor returns directly to Library without restarting OAuth', async () => {
  const storage = new Map([[AUTH_KEY, JSON.stringify({ accessToken: 'still-valid', expiresAt: Date.now() + 600_000 })]]);
  const page = analyzer(storage, '?login=library');
  for (let i = 0; i < 3; i++) await page.settle();
  assert.deepEqual(page.calls.replaced, ['/library/']);
  assert.equal(page.calls.assigned.length, 0);
  assert.equal(storage.has(PKCE_KEY), false);
});

test('OAuth error or forged return path never sends a visitor to arbitrary destinations', async () => {
  const storage = new Map([[PKCE_KEY, JSON.stringify({
    state: 'test-state', verifier: 'test-verifier', createdAt: Date.now(),
    returnTo: 'https://malicious.example/'
  })]]);
  const callback = analyzer(storage, '?code=code&state=test-state', async () => ({
    ok: true, status: 200, json: async () => ({ access_token: 'ok', expires_in: 3600 })
  }));
  for (let i = 0; i < 3; i++) await callback.settle();
  assert.deepEqual(callback.calls.replaced, [], 'Only the fixed same-origin library path is allowed');
  assert.equal(JSON.parse(storage.get(AUTH_KEY)).accessToken, 'ok');
});
