/* Premium grants are managed by authenticated server routes, never by browser email claims. */
(() => {
  'use strict';

  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const SUBJECT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const $ = id => document.getElementById(id);
  const ui = {
    notice: $('premium-admin-notice'), controls: $('premium-admin-controls'),
    runtime: $('premium-admin-runtime'), search: $('premium-user-search'),
    email: $('premium-search-email'), find: $('premium-find-user'),
    result: $('premium-user-result'), userEmail: $('premium-user-email'),
    userId: $('premium-user-id'), state: $('premium-user-state'),
    change: $('premium-change-form'), reason: $('premium-change-reason'),
    action: $('premium-change-button')
  };
  if (Object.values(ui).some(element => !element)) return;
  let apiBase = '';
  try {
    const url = new URL((window.STROKESENSE_AWS_CONFIG || {}).apiBaseUrl);
    if (url.protocol === 'https:') apiBase = url.origin;
  } catch (_) { /* Configuration is checked before making any request. */ }

  let authorized = false;
  let busy = false;
  let selected = null;
  let generation = 0;

  function readAuth() {
    try {
      const value = JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null');
      return typeof value?.accessToken === 'string' && value.accessToken &&
        value.expiresAt > Date.now() + 15000 ? value : null;
    } catch (_) { return null; }
  }

  function notice(message, tone = '') {
    ui.notice.textContent = message;
    ui.notice.dataset.tone = tone;
  }

  function clearUser() {
    selected = null;
    ui.result.hidden = true;
    ui.userEmail.textContent = '';
    ui.userId.textContent = '';
    ui.state.textContent = '';
    ui.reason.value = '';
    ui.action.disabled = true;
  }

  function setBusy(value) {
    busy = value;
    ui.email.disabled = value;
    ui.find.disabled = value;
    const protectedOwner = selected?.premium_access?.owner_protected === true;
    ui.reason.disabled = value || protectedOwner;
    ui.action.disabled = value || !authorized || !selected || protectedOwner;
  }

  function lock(message) {
    authorized = false;
    generation += 1;
    clearUser();
    ui.controls.hidden = true;
    ui.runtime.textContent = '';
    notice(message, 'error');
  }

  function userView(value) {
    if (!value || typeof value.user_id !== 'string' || !SUBJECT.test(value.user_id) ||
        typeof value.email !== 'string' || value.email.length > 254 || value.email_verified !== true ||
        typeof value.premium_access?.granted !== 'boolean') return null;
    return value;
  }

  function showUser(user) {
    selected = user;
    ui.userEmail.textContent = user.email;
    ui.userId.textContent = user.user_id;
    ui.state.textContent = user.premium_access.granted ? 'Premium access granted' : 'Premium access not granted';
    ui.state.dataset.tone = user.premium_access.granted ? 'ready' : 'muted';
    ui.action.textContent = user.premium_access.owner_protected === true ? 'Owner access protected' :
      user.premium_access.granted ? 'Revoke Premium access' : 'Grant Premium access';
    ui.action.dataset.action = user.premium_access.granted ? 'revoke' : 'grant';
    ui.reason.value = '';
    ui.result.hidden = false;
    ui.action.disabled = busy || !authorized || user.premium_access.owner_protected === true;
  }

  async function request(path, options = {}) {
    const auth = readAuth();
    if (!auth) {
      lock('Sign in with an administrator account to manage Premium access.');
      throw Object.assign(Error('Sign-in required.'), { status: 401 });
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + path, {
        method: options.body ? 'POST' : 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken,
          ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
        body: options.body ? JSON.stringify(options.body) : undefined, signal: controller.signal
      });
      if (readAuth()?.accessToken !== auth.accessToken) {
        lock('Your sign-in changed. Reload the admin page to check access again.');
        throw Object.assign(Error('Sign-in changed.'), { status: 401 });
      }
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        lock('Your sign-in expired. Sign in again to manage Premium access.');
        throw Object.assign(Error('Sign-in expired.'), { status: 401 });
      }
      let payload;
      try { payload = await response.json(); } catch (_) { payload = {}; }
      if (readAuth()?.accessToken !== auth.accessToken) {
        lock('Your sign-in changed. Reload the admin page to check access again.');
        throw Object.assign(Error('Sign-in changed.'), { status: 401 });
      }
      if (!response.ok) throw Object.assign(Error('Premium access request failed.'), {
        status: response.status, code: payload.error?.code || ''
      });
      return payload;
    } finally { clearTimeout(timer); }
  }

  async function authorize() {
    clearUser();
    ui.controls.hidden = true;
    if (!apiBase) { notice('Premium management is waiting for the AWS API configuration.', 'error'); return; }
    if (!readAuth()) { notice('Sign in with an administrator account to manage Premium access.'); return; }
    try {
      const account = await request('/me');
      if (account?.is_admin !== true) {
        lock('This account does not have permission to manage Premium access.');
        return;
      }
      authorized = true;
      ui.controls.hidden = false;
      ui.runtime.textContent = account.premium_access?.available === true
        ? 'Premium access changes take effect for future analyses.'
        : 'You can manage Premium access now. GPU analysis is not available yet.';
      notice('Find a user by their exact Google sign-in email to manage Premium access.');
      setBusy(false);
    } catch (error) {
      if (error.status === 401) return;
      lock(error.status === 403 ? 'This account does not have permission to manage Premium access.'
        : 'Premium management is unavailable. Reload this page to check again.');
    }
  }

  async function findUser(event) {
    event.preventDefault();
    if (!authorized || busy) return;
    clearUser();
    const email = ui.email.value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
      notice('Enter the full email address the user uses to sign in with Google.', 'error');
      return;
    }
    const current = ++generation;
    setBusy(true);
    notice('Looking up the verified account…');
    try {
      const result = await request('/admin/users?email=' + encodeURIComponent(email));
      if (current !== generation) return;
      const user = Array.isArray(result?.users) && result.users.length === 1 ? userView(result.users[0]) : null;
      if (!user || user.email.toLowerCase() !== email.toLowerCase()) {
        notice('No unique verified account was returned. Ask the user to sign in once, then check the exact email.', 'error');
        return;
      }
      showUser(user);
      notice(user.premium_access.owner_protected === true
        ? 'Verified owner account. The owner’s Premium access is protected.'
        : 'Verified account found. Check the email and account ID before changing access.');
    } catch (error) {
      if (current !== generation || error.status === 401) return;
      if (error.status === 403) {
        lock('Your account no longer has permission to manage Premium access.');
      } else if (error.status === 404 || error.code === 'premium_user_not_found') {
        notice('No verified account matches that email. Ask the user to sign in with Google once, then try again.', 'error');
      } else if (error.code === 'premium_identity_ambiguous') {
        notice('More than one account matches that email. Account records must be resolved before access can change.', 'error');
      } else {
        notice('The user lookup could not be completed. No access change was requested.', 'error');
      }
    } finally {
      setBusy(false);
    }
  }

  async function changeAccess(event) {
    event.preventDefault();
    if (!authorized || busy || !selected || selected.premium_access.owner_protected === true) return;
    const reason = ui.reason.value.trim();
    if (reason.length < 3 || reason.length > 500 || /\p{C}/u.test(reason)) {
      notice('Enter a reason between 3 and 500 visible characters on one line for this access change.', 'error');
      return;
    }
    const target = selected;
    const enabled = !target.premium_access.granted;
    const current = ++generation;
    setBusy(true);
    notice((enabled ? 'Granting' : 'Revoking') + ' Premium access for ' + target.email + '…');
    try {
      const result = userView(await request('/admin/users/' + encodeURIComponent(target.user_id) + '/premium', {
        body: { enabled, reason }
      }));
      if (current !== generation) return;
      if (!result || result.user_id !== target.user_id || result.premium_access.granted !== enabled) {
        throw Error('Access change was not confirmed.');
      }
      showUser(result);
      notice('Premium access ' + (enabled ? 'granted to ' : 'revoked for ') + result.email +
        '. The change has been recorded.', 'success');
    } catch (error) {
      if (current !== generation || error.status === 401) return;
      if (error.code === 'premium_owner_protected') {
        notice('The owner’s Premium access is protected and cannot be revoked here.', 'error');
      } else if (error.status === 403) {
        lock('Your account no longer has permission to manage Premium access.');
      } else {
        clearUser();
        notice(error.code === 'premium_access_conflict'
          ? 'This account changed while you were editing. Find the user again to review their current access.'
          : 'The access change could not be confirmed. Find this user again to check their current access before retrying.', 'error');
      }
    } finally { setBusy(false); }
  }

  ui.email.addEventListener('input', () => {
    if (busy) return;
    generation += 1;
    clearUser();
  });
  ui.search.addEventListener('submit', findUser);
  ui.change.addEventListener('submit', changeAccess);
  authorize();
})();
