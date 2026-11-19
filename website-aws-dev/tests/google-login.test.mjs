import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');

function browserWithOAuthResponse(query, { pending, tokenResponse } = {}) {
  const elements = new Map();
  const storage = new Map();
  const requests = [];
  const replacedUrls = [];
  if (pending) storage.set('strokesense-aws-dev-pkce', JSON.stringify(pending));
  const element = id => {
    if (!elements.has(id)) {
      elements.set(id, {
        dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
        addEventListener() {}, removeAttribute() {}, textContent: '',
        checked: id === 'tier-free', hidden: false, disabled: false
      });
    }
    return elements.get(id);
  };

  runInNewContext(client, {
    document: { getElementById: element, querySelectorAll: () => [] },
    window: {
      STROKESENSE_AWS_CONFIG: {
        apiBaseUrl: 'https://example.execute-api.us-east-1.amazonaws.com',
        cognitoDomain: 'https://example.auth.us-east-1.amazoncognito.com',
        cognitoClientId: 'public-client'
      },
      location: { origin: 'https://strokesense-aws-dev.vercel.app', search: query, hash: '' }
    },
    history: { replaceState(_state, _title, url) { replacedUrls.push(url); } },
    sessionStorage: {
      getItem(key) { return storage.get(key) || null; },
      setItem(key, value) { storage.set(key, value); },
      removeItem(key) { storage.delete(key); }
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return {
        ok: tokenResponse?.ok ?? true,
        status: tokenResponse?.status ?? 200,
        json: async () => tokenResponse?.json ?? { access_token: 'test-access-token', expires_in: 3600 }
      };
    },
    URL, URLSearchParams, AbortController
  });
  return {
    elements, storage, requests, replacedUrls,
    async settle() { await new Promise(resolve => setImmediate(resolve)); }
  };
}

test('Cognito callback error displays a bounded diagnostic and clears pending PKCE state', async () => {
  const description = encodeURIComponent('Invalid callback URL.\nPlease check Cognito settings.');
  const app = browserWithOAuthResponse(`?error=invalid_request&error_description=${description}`, {
    pending: { verifier: 'abc', state: 'xyz', createdAt: Date.now() }
  });
  await app.settle();
  assert.equal(app.replacedUrls[0], 'https://strokesense-aws-dev.vercel.app/demos/');
  assert.equal(app.storage.has('strokesense-aws-dev-pkce'), false);
  assert.match(app.elements.get('auth-feedback').textContent, /invalid_request: Invalid callback URL\. Please check Cognito settings/);
  assert.equal(app.elements.get('auth-feedback').dataset.tone, 'error');
  assert.equal(app.requests.length, 0);
});

test('token exchange failure exposes Cognito error code without exposing the authorization code', async () => {
  const app = browserWithOAuthResponse('?code=sensitive-code&state=known-state', {
    pending: { verifier: 'test-verifier', state: 'known-state', createdAt: Date.now() },
    tokenResponse: {
      ok: false, status: 400,
      json: { error: 'invalid_grant', error_description: 'Code verifier did not match' }
    }
  });
  await app.settle();
  const message = app.elements.get('auth-feedback').textContent;
  assert.match(message, /invalid_grant: Code verifier did not match/);
  assert.doesNotMatch(message, /sensitive-code/);
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].url, 'https://example.auth.us-east-1.amazoncognito.com/oauth2/token');
  assert.equal(app.requests[0].options.body.get('code_verifier'), 'test-verifier');
  assert.equal(app.storage.has('strokesense-aws-dev-auth'), false);
});

test('successful Google callback stores short-lived authentication tokens', async () => {
  const app = browserWithOAuthResponse('?code=test-code&state=known-state', {
    pending: { verifier: 'test-verifier', state: 'known-state', createdAt: Date.now() }
  });
  await app.settle();
  assert.match(app.elements.get('auth-feedback').textContent, /sign-in successful/);
  assert.equal(app.elements.get('google-login').hidden, true);
  assert.equal(JSON.parse(app.storage.get('strokesense-aws-dev-auth')).accessToken, 'test-access-token');
});

test('private history deep link stores only a valid job ID and clears the URL query', async () => {
  const id = '8d323d41ed3a4ffcaee778201670098e';
  const app = browserWithOAuthResponse('?job=' + id);
  await app.settle();
  assert.equal(app.storage.get('strokesense-aws-dev-active-job'), id);
  assert.equal(app.replacedUrls[0], 'https://strokesense-aws-dev.vercel.app/demos/');
  assert.equal(app.requests.length, 0);

  const invalid = browserWithOAuthResponse('?job=..%2Fother-user');
  await invalid.settle();
  assert.equal(invalid.storage.has('strokesense-aws-dev-active-job'), false);
  assert.equal(invalid.requests.length, 0);
});
