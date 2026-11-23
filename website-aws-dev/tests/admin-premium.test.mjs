import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../assets/admin-premium.js', import.meta.url), 'utf8');
const AUTH = 'strokesense-aws-dev-auth';
const API = 'https://example.execute-api.us-east-1.amazonaws.com';
const ID = '9e630dea-6c61-4e04-ae4d-55a0918c72b6';
const user = (granted = false, overrides = {}) => ({
  user_id: ID, email: 'rower@example.com', email_verified: true,
  premium_access: { granted, source: 'admin', updated_at: 1795392000 }, ...overrides
});
const admin = { is_admin: true, premium_access: { granted: true, available: false } };
const reply = (body, status = 200) => ({ status, ok: status < 400, json: async () => body });

function browser({ signedIn = true, responses = [reply(admin)] } = {}) {
  const elements = new Map();
  const requests = [];
  const storage = new Map();
  if (signedIn) storage.set(AUTH, JSON.stringify({ accessToken: 'admin-token', expiresAt: Date.now() + 600000 }));
  class Element {
    constructor() { this.hidden = false; this.disabled = false; this.value = ''; this.textContent = ''; this.dataset = {}; this.listeners = new Map(); }
    addEventListener(name, action) { this.listeners.set(name, action); }
    dispatch(name) { return this.listeners.get(name)?.({ preventDefault() {} }); }
    set innerHTML(_) { throw Error('Private account identity must be rendered as text.'); }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  runInNewContext(source, {
    window: { STROKESENSE_AWS_CONFIG: { apiBaseUrl: API } },
    document: { getElementById: element },
    sessionStorage: { getItem: key => storage.get(key) || null, removeItem: key => storage.delete(key) },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const next = responses.shift();
      if (!next) throw Error('Unexpected extra request');
      return typeof next === 'function' ? next(url, options) : next;
    },
    URL, AbortController, setTimeout, clearTimeout
  });
  return { elements, requests, storage,
    async settle() { await new Promise(resolve => setImmediate(resolve)); },
    async find(email = 'rower@example.com') {
      element('premium-search-email').value = email;
      await element('premium-user-search').dispatch('submit');
    },
    async change(reason = 'Approved for the Premium pilot') {
      element('premium-change-reason').value = reason;
      await element('premium-change-form').dispatch('submit');
    }
  };
}

test('signed-out and non-admin visitors cannot query users or request grants', async () => {
  for (const signedIn of [false, true]) {
    const page = browser({ signedIn, responses: [reply({ is_admin: false })] });
    await page.settle();
    await page.find();
    await page.change();
    assert.equal(page.elements.get('premium-admin-controls').hidden, true);
    assert.equal(page.elements.get('premium-user-result').hidden, true);
    assert.equal(page.requests.length, signedIn ? 1 : 0);
  }
});

test('an admin verifies a stable account, then explicitly grants and revokes Premium with an audit reason', async () => {
  const page = browser({ responses: [reply(admin), reply({ users: [user()] }), reply(user(true)), reply(user(false))] });
  await page.settle();
  assert.equal(page.elements.get('premium-admin-controls').hidden, false);
  assert.match(page.elements.get('premium-admin-runtime').textContent, /not available yet/);
  await page.find('rower@example.com');
  assert.equal(page.requests.length, 2, 'lookup must never grant access automatically');
  assert.equal(new URL(page.requests[1].url).searchParams.get('email'), 'rower@example.com');
  assert.equal(page.elements.get('premium-user-id').textContent, ID);
  assert.equal(page.elements.get('premium-user-email').textContent, 'rower@example.com');
  await page.change();
  assert.equal(page.requests[2].url, API + '/admin/users/' + ID + '/premium');
  assert.equal(page.requests[2].options.method, 'POST');
  assert.equal(page.requests[2].options.headers.Authorization, 'Bearer admin-token');
  assert.deepEqual(JSON.parse(page.requests[2].options.body), { enabled: true, reason: 'Approved for the Premium pilot' });
  assert.equal(page.elements.get('premium-user-state').textContent, 'Premium access granted');
  assert.equal(page.elements.get('premium-change-button').textContent, 'Revoke Premium access');
  await page.change('Pilot access ended');
  assert.deepEqual(JSON.parse(page.requests[3].options.body), { enabled: false, reason: 'Pilot access ended' });
  assert.equal(page.elements.get('premium-user-state').textContent, 'Premium access not granted');
});

test('unverified, ambiguous, mismatched and malformed identities cannot become mutation targets', async () => {
  for (const users of [
    [user(false, { email_verified: false })], [user(), user()],
    [user(false, { email: 'someone-else@example.com' })],
    [user(false, { user_id: '../../other-account' })], []
  ]) {
    const page = browser({ responses: [reply(admin), reply({ users })] });
    await page.settle();
    await page.find();
    await page.change();
    assert.equal(page.elements.get('premium-user-result').hidden, true);
    assert.equal(page.requests.length, 2);
  }
});

test('editing the search email discards the prior target and blocks accidental changes', async () => {
  const page = browser({ responses: [reply(admin), reply({ users: [user()] })] });
  await page.settle();
  await page.find();
  page.elements.get('premium-search-email').value = 'new@example.com';
  page.elements.get('premium-search-email').dispatch('input');
  await page.change();
  assert.equal(page.elements.get('premium-user-result').hidden, true);
  assert.equal(page.requests.length, 2);
});

test('a missing reason cannot send an access change', async () => {
  const page = browser({ responses: [reply(admin), reply({ users: [user()] })] });
  await page.settle();
  await page.find();
  await page.change('  ');
  assert.equal(page.requests.length, 2);
  assert.match(page.elements.get('premium-admin-notice').textContent, /3 and 500/);
});

test('duplicate submits cannot issue concurrent Premium mutations', async () => {
  let finish;
  const page = browser({ responses: [reply(admin), reply({ users: [user()] }), () => new Promise(resolve => { finish = resolve; })] });
  await page.settle();
  await page.find();
  const first = page.change();
  await page.settle();
  await page.change();
  assert.equal(page.requests.length, 3);
  assert.equal(page.elements.get('premium-change-button').disabled, true);
  finish(reply(user(true)));
  await first;
  assert.equal(page.elements.get('premium-change-button').disabled, false);
});

test('a failed mutation is never retried automatically or reported as successful', async () => {
  const page = browser({ responses: [reply(admin), reply({ users: [user()] }), () => { throw Error('Connection lost'); }] });
  await page.settle();
  await page.find();
  await page.change();
  await page.settle();
  assert.equal(page.requests.length, 3);
  assert.equal(page.elements.get('premium-user-result').hidden, true);
  assert.match(page.elements.get('premium-admin-notice').textContent, /could not be confirmed/);
});

test('protected owner access stays granted after a rejected revocation', async () => {
  const page = browser({ responses: [reply(admin), reply({ users: [user(true)] }), reply({ error: { code: 'premium_owner_protected' } }, 403)] });
  await page.settle();
  await page.find();
  await page.change();
  assert.equal(page.elements.get('premium-user-state').textContent, 'Premium access granted');
  assert.match(page.elements.get('premium-admin-notice').textContent, /protected/);
});

test('the verified owner account is presented as protected without offering a revocation', async () => {
  const owner = user(true, { premium_access: { granted: true, owner_protected: true } });
  const page = browser({ responses: [reply(admin), reply({ users: [owner] })] });
  await page.settle();
  await page.find();
  await page.change();
  assert.equal(page.elements.get('premium-change-button').disabled, true);
  assert.equal(page.elements.get('premium-change-button').textContent, 'Owner access protected');
  assert.equal(page.requests.length, 2);
});

test('an expired or revoked admin session clears the selected private identity and all controls', async () => {
  for (const status of [401, 403]) {
    const page = browser({ responses: [reply(admin), reply({ users: [user()] }), reply({}, status)] });
    await page.settle();
    await page.find();
    await page.change();
    assert.equal(page.elements.get('premium-admin-controls').hidden, true);
    assert.equal(page.elements.get('premium-user-email').textContent, '');
    assert.equal(page.elements.get('premium-user-id').textContent, '');
    if (status === 401) assert.equal(page.storage.has(AUTH), false);
  }
});

test('account identity is displayed as literal text and never trusted markup', async () => {
  const email = '<img+onerror=alert(1)>@example.com';
  const page = browser({ responses: [reply(admin), reply({ users: [user(false, { email })] })] });
  await page.settle();
  await page.find(email);
  assert.equal(page.elements.get('premium-user-email').textContent, email);
  assert.equal(page.elements.get('premium-user-result').hidden, false);
});
