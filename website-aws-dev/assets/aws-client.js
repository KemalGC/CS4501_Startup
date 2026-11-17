/* Isolated AWS development client. Never calls the production Render service. */
(() => {
  'use strict';

  const config = window.STROKESENSE_AWS_CONFIG || {};
  const FREE_VIDEO_BYTES = 100_000_000;
  const PAID_VIDEO_BYTES = 750_000_000;
  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const PKCE_KEY = 'strokesense-aws-dev-pkce';
  const $ = id => document.getElementById(id);
  const ui = {
    backendStatus: $('backend-status'), backendDetail: $('backend-detail'),
    login: $('google-login'), logout: $('google-logout'), account: $('account-status'),
    tierFree: $('tier-free'), tierPaid: $('tier-paid'), fileLimit: $('file-limit'),
    input: $('video-upload'), dropzone: $('dropzone'), fileReview: $('file-review'),
    fileName: $('selected-file-name'), fileSize: $('selected-file-size'),
    clear: $('clear-file'), video: $('local-preview'), run: $('run-analysis'),
    cancel: $('cancel-upload'), helper: $('run-helper'), feedback: $('upload-feedback'),
    progress: $('analysis-progress'), progressBar: $('analysis-progress-bar'),
    percentage: $('analysis-percentage'), status: $('analysis-status'),
    detail: $('analysis-detail'), result: $('analysis-result'), download: $('download-report')
  };

  const sanitizeUrl = value => {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value);
      return url.protocol === 'https:' ? url.origin : '';
    } catch (_) { return ''; }
  };
  const cognitoDomain = sanitizeUrl(config.cognitoDomain);
  const apiBase = sanitizeUrl(config.apiBaseUrl);
  const clientId = typeof config.cognitoClientId === 'string' ? config.cognitoClientId.trim() : '';
  const loginReady = Boolean(cognitoDomain && clientId);
  const backendReady = Boolean(loginReady && apiBase);
  const deepAnalysisEnabled = config.deepAnalysisEnabled === true;
  const redirectUri = window.location.origin + '/demos/';
  let file = null;
  let localVideoUrl = '';
  let busy = false;
  let abortController = null;
  let activeVideoId = null;

  function feedback(message, tone = '') {
    ui.feedback.textContent = message;
    ui.feedback.dataset.tone = tone;
  }
  function tier() { return ui.tierPaid.checked ? 'paid' : 'free'; }
  function limit() { return tier() === 'paid' ? PAID_VIDEO_BYTES : FREE_VIDEO_BYTES; }
  function formatMB(bytes) { return (bytes / 1_000_000).toFixed(1).replace(/\.0$/, '') + ' MB'; }

  function readAuth() {
    try {
      const result = JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null');
      return result && result.accessToken && result.expiresAt > Date.now() + 15_000 ? result : null;
    } catch (_) { return null; }
  }
  function clearAuth() {
    try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
  }
  function userLabel(auth) {
    if (!auth || !auth.idToken) return 'Signed in with Google.';
    try {
      const payload = auth.idToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const user = JSON.parse(atob(payload));
      return typeof user.email === 'string' ? 'Signed in as ' + user.email : 'Signed in with Google.';
    } catch (_) { return 'Signed in with Google.'; }
  }

  function render() {
    const auth = readAuth();
    const selectedTier = tier();
    document.querySelectorAll('.aws-tier-card').forEach(card => {
      card.classList.toggle('is-selected', card.querySelector('input').checked);
    });
    ui.fileLimit.textContent = 'Up to ' + formatMB(limit());
    ui.login.hidden = Boolean(auth);
    ui.login.disabled = !loginReady;
    ui.logout.hidden = !auth;
    ui.account.textContent = auth ? userLabel(auth) :
      loginReady ? 'Sign in with Google to track your lifetime allowance and private reports.' :
        'Google sign-in is waiting for the Cognito user pool and OAuth client.';
    if (!apiBase) {
      ui.backendStatus.textContent = 'AWS backend is not provisioned — interface preview only';
      ui.backendDetail.textContent = 'Choose a tier and check local video limits. The preview cannot upload or analyze files until you explicitly approve AWS provisioning.';
    } else if (!loginReady) {
      ui.backendStatus.textContent = 'AWS API configured; Google login is not configured';
      ui.backendDetail.textContent = 'Configure the Cognito domain and public client ID before submitting private analysis jobs.';
    } else {
      ui.backendStatus.textContent = 'AWS configuration present';
      ui.backendDetail.textContent = 'This staging website uses its own AWS endpoint, separate from the Render-backed production site.';
    }
    const tooLarge = file && file.size > limit();
    const ready = backendReady && auth && file && !tooLarge && !busy &&
      (selectedTier === 'free' || deepAnalysisEnabled);
    ui.run.disabled = !ready;
    ui.run.textContent = busy ? 'Analysis in progress…' : selectedTier === 'paid' ? 'Start Deep Analysis' : 'Start Free Analysis';
    if (tooLarge) {
      ui.helper.textContent = 'The selected video exceeds the ' + formatMB(limit()) + ' per-video limit.';
    } else if (selectedTier === 'paid' && !deepAnalysisEnabled) {
      ui.helper.textContent = 'Deep Analysis credit purchases and GPU processing remain disabled until billing and compute are approved.';
    } else if (!backendReady) {
      ui.helper.textContent = 'Local video checks work now. AWS analysis unlocks after the backend and Cognito are provisioned.';
    } else if (!auth) {
      ui.helper.textContent = 'Sign in with Google to upload and start an analysis.';
    } else {
      ui.helper.textContent = 'Ready to submit a private ' + selectedTier + ' analysis job.';
    }
  }

  function setFile(nextFile) {
    if (localVideoUrl) URL.revokeObjectURL(localVideoUrl);
    file = nextFile || null;
    ui.result.hidden = true;
    ui.video.hidden = !file;
    ui.fileReview.hidden = !file;
    if (!file) {
      ui.video.removeAttribute('src');
      ui.input.value = '';
      feedback('');
      render();
      return;
    }
    const accepted = /\.(mp4|mov|webm)$/i.test(file.name) && file.size > 0;
    ui.fileName.textContent = file.name;
    ui.fileSize.textContent = formatMB(file.size) + ' · ' + (accepted ? 'Supported file extension' : 'Unsupported or empty file');
    localVideoUrl = URL.createObjectURL(file);
    ui.video.src = localVideoUrl;
    if (!accepted) {
      feedback('Select a nonempty MP4, MOV, or WebM file.', 'error');
      file = null;
    } else if (file.size > limit()) {
      feedback('This video is larger than the ' + formatMB(limit()) + ' limit for this tier.', 'error');
    } else {
      feedback('Local file check passed. No video has been uploaded.', 'success');
    }
    render();
  }

  const base64url = bytes => btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  async function signIn() {
    if (!loginReady) return;
    const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
    const state = base64url(crypto.getRandomValues(new Uint8Array(16)));
    try { sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state, createdAt: Date.now() })); }
    catch (_) { feedback('Browser storage is required to complete Google sign-in.', 'error'); return; }
    const url = new URL(cognitoDomain + '/oauth2/authorize');
    url.searchParams.set('client_id', clientId);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('scope', 'openid email profile');
    url.searchParams.set('redirect_uri', redirectUri);
    url.searchParams.set('identity_provider', 'Google');
    url.searchParams.set('code_challenge_method', 'S256');
    url.searchParams.set('code_challenge', challenge);
    url.searchParams.set('state', state);
    window.location.assign(url.toString());
  }

  async function finishSignIn() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const error = params.get('error');
    if (!code && !error) return;
    history.replaceState(null, '', redirectUri + window.location.hash);
    if (error) { feedback('Google sign-in did not complete: ' + error, 'error'); return; }
    let pending;
    try { pending = JSON.parse(sessionStorage.getItem(PKCE_KEY) || 'null'); sessionStorage.removeItem(PKCE_KEY); }
    catch (_) { pending = null; }
    if (!pending || !pending.verifier || params.get('state') !== pending.state || Date.now() - pending.createdAt > 600_000) {
      feedback('Sign-in session verification failed. Please retry Google login.', 'error');
      return;
    }
    try {
      const body = new URLSearchParams({
        grant_type: 'authorization_code', client_id: clientId, code,
        redirect_uri: redirectUri, code_verifier: pending.verifier
      });
      const response = await fetch(cognitoDomain + '/oauth2/token', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body, credentials: 'omit'
      });
      const result = await response.json();
      if (!response.ok || !result.access_token) throw Error('Cognito did not return an access token.');
      sessionStorage.setItem(AUTH_KEY, JSON.stringify({
        accessToken: result.access_token, idToken: result.id_token || '',
        expiresAt: Date.now() + Math.max(0, Number(result.expires_in || 3600) - 60) * 1000
      }));
      feedback('Google sign-in successful.', 'success');
    } catch (_) { feedback('Unable to complete Google sign-in. Check the Cognito callback and public client configuration.', 'error'); }
    render();
  }

  async function api(path, { method = 'GET', body, signal } = {}) {
    const auth = readAuth();
    if (!auth) throw Error('Your sign-in expired. Sign in with Google again.');
    if (!apiBase) throw Error('The AWS API is not configured yet.');
    const response = await fetch(apiBase + path, {
      method, signal, credentials: 'omit',
      headers: { Authorization: 'Bearer ' + auth.accessToken, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined
    });
    let payload;
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) throw Error(typeof payload.message === 'string' ? payload.message :
      typeof payload.error?.message === 'string' ? payload.error.message :
        typeof payload.error === 'string' ? payload.error : 'AWS request failed (' + response.status + ').');
    return payload;
  }

  function progress(label, percentage, detail = '') {
    ui.progress.hidden = false;
    ui.status.textContent = label;
    ui.percentage.textContent = percentage + '%';
    ui.progressBar.value = percentage;
    ui.detail.textContent = detail;
  }

  async function uploadMultipart(upload, signal) {
    const partSize = Number(upload.part_size_bytes);
    const partCount = Number(upload.part_count);
    if (!Number.isSafeInteger(partSize) || partSize < 5 * 1024 * 1024 ||
        !Number.isSafeInteger(partCount) || partCount < 1 || partCount > 10000 ||
        partCount !== Math.ceil(file.size / partSize)) {
      throw Error('The AWS backend returned invalid multipart upload configuration.');
    }
    const parts = [];
    let nextPart = 1;
    async function worker() {
      while (nextPart <= partCount) {
        const partNumber = nextPart++;
        const signed = await api('/uploads/part', {
          method: 'POST', body: { video_id: upload.video_id, part_number: partNumber }, signal
        });
        const target = new URL(signed.url);
        if (target.protocol !== 'https:') throw Error('The upload URL is not secure.');
        const response = await fetch(target.toString(), {
          method: 'PUT', body: file.slice((partNumber - 1) * partSize, Math.min(partNumber * partSize, file.size)), signal
        });
        if (!response.ok) throw Error('An S3 upload part failed (' + response.status + ').');
        const etag = response.headers.get('ETag');
        if (!etag) throw Error('S3 upload response did not expose ETag. Check bucket CORS.');
        parts.push({ part_number: partNumber, etag });
        progress('Uploading video', Math.round(parts.length / partCount * 90),
          parts.length + ' of ' + partCount + ' parts uploaded');
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, partCount) }, worker));
    return parts.sort((a, b) => a.part_number - b.part_number);
  }

  async function waitForAnalysis(jobId, signal) {
    const deadline = Date.now() + 30 * 60 * 1000;
    while (Date.now() < deadline) {
      if (signal.aborted) throw Error('Upload cancelled.');
      const job = await api('/analysis/jobs/' + encodeURIComponent(jobId), { signal });
      const state = String(job.status || '').toLowerCase();
      if (['completed', 'succeeded', 'finished'].includes(state)) {
        progress('Analysis completed', 100, 'Preparing your private report download.');
        const report = await api('/reports/' + encodeURIComponent(jobId), { signal });
        if (!report.download_url || new URL(report.download_url).protocol !== 'https:') {
          throw Error('The report is complete but a secure download URL is unavailable.');
        }
        ui.download.href = report.download_url;
        ui.result.hidden = false;
        feedback('Your report is ready. Download it before it expires.', 'success');
        return;
      }
      if (['failed', 'cancelled', 'error'].includes(state)) {
        throw Error('Analysis ' + state + '. Your reserved allowance will be returned by the backend.');
      }
      progress('Analyzing with AWS', Math.max(90, Math.min(99, Number(job.progress || 90))),
        'Status: ' + (state || 'queued'));
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, 5000);
        signal.addEventListener('abort', () => { clearTimeout(timer); reject(Error('Cancelled.')); }, { once: true });
      });
    }
    throw Error('Analysis is still running. Return later after the backend supports job history.');
  }

  async function startAnalysis() {
    if (busy || !backendReady || !readAuth() || !file || file.size > limit()) return;
    if (tier() === 'paid' && !deepAnalysisEnabled) return;
    busy = true;
    activeVideoId = null;
    let jobSubmitted = false;
    abortController = new AbortController();
    ui.result.hidden = true;
    ui.cancel.hidden = false;
    render();
    try {
      progress('Reserving upload', 0, 'Checking your allowance and creating a private S3 upload.');
      const upload = await api('/uploads/start', {
        method: 'POST', body: {
          filename: file.name, content_type: file.type || 'application/octet-stream',
          size_bytes: file.size, tier: tier()
        }, signal: abortController.signal
      });
      activeVideoId = upload.video_id;
      const parts = await uploadMultipart(upload, abortController.signal);
      progress('Finalizing upload', 92, 'Verifying your video in private storage.');
      await api('/uploads/complete', {
        method: 'POST', body: { video_id: upload.video_id, parts }, signal: abortController.signal
      });
      progress('Submitting analysis', 95, 'Scheduling an independent analysis job.');
      const job = await api('/analysis/jobs', {
        method: 'POST', body: { video_id: upload.video_id }, signal: abortController.signal
      });
      jobSubmitted = true;
      activeVideoId = null;
      ui.cancel.hidden = true;
      await waitForAnalysis(job.job_id, abortController.signal);
    } catch (error) {
      // Once a job was submitted, only its server-side lifecycle can refund it.
      if (activeVideoId && !jobSubmitted) {
        try { await api('/uploads/abort', { method: 'POST', body: { video_id: activeVideoId } }); }
        catch (_) { /* The backend also reclaims abandoned reservations. */ }
      }
      feedback(error && error.message ? error.message : 'The upload could not be completed.', 'error');
      progress('Unable to finish analysis', 0, 'No report was generated.');
    } finally {
      busy = false;
      activeVideoId = null;
      abortController = null;
      ui.cancel.hidden = true;
      render();
    }
  }

  ui.login.addEventListener('click', signIn);
  ui.logout.addEventListener('click', () => { clearAuth(); feedback('Signed out of this preview.'); render(); });
  ui.tierFree.addEventListener('change', render);
  ui.tierPaid.addEventListener('change', render);
  ui.input.addEventListener('change', () => setFile(ui.input.files[0]));
  ui.clear.addEventListener('click', () => setFile(null));
  ui.dropzone.addEventListener('dragover', event => { event.preventDefault(); ui.dropzone.classList.add('is-dragover'); });
  ui.dropzone.addEventListener('dragleave', () => ui.dropzone.classList.remove('is-dragover'));
  ui.dropzone.addEventListener('drop', event => {
    event.preventDefault();
    ui.dropzone.classList.remove('is-dragover');
    if (event.dataTransfer.files.length) setFile(event.dataTransfer.files[0]);
  });
  ui.cancel.addEventListener('click', () => abortController?.abort());
  ui.run.addEventListener('click', startAnalysis);
  render();
  finishSignIn();
})();
