/* Isolated AWS development client. Never calls the production Render service. */
(() => {
  'use strict';

  const config = window.STROKESENSE_AWS_CONFIG || {};
  const FREE_VIDEO_BYTES = 100_000_000;
  const PAID_VIDEO_BYTES = 750_000_000;
  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const PKCE_KEY = 'strokesense-aws-dev-pkce';
  const ACTIVE_JOB_KEY = 'strokesense-aws-dev-active-job';
  const $ = id => document.getElementById(id);
  const ui = {
    backendStatus: $('backend-status'), backendDetail: $('backend-detail'),
    login: $('google-login'), logout: $('google-logout'), account: $('account-status'),
    authFeedback: $('auth-feedback'),
    tierFree: $('tier-free'), tierPaid: $('tier-paid'), fileLimit: $('file-limit'),
    input: $('video-upload'), dropzone: $('dropzone'), fileReview: $('file-review'),
    fileName: $('selected-file-name'), fileSize: $('selected-file-size'),
    clear: $('clear-file'), video: $('local-preview'), run: $('run-analysis'),
    cancel: $('cancel-upload'), helper: $('run-helper'), feedback: $('upload-feedback'),
    progress: $('analysis-progress'), progressBar: $('analysis-progress-bar'),
    percentage: $('analysis-percentage'), status: $('analysis-status'),
    detail: $('analysis-detail'), result: $('analysis-result'), download: $('download-report'),
    reportPreview: $('report-preview'), reportFrame: $('report-frame'),
    stages: { upload: $('analysis-stage-upload'), analysis: $('analysis-stage-analysis'),
      report: $('analysis-stage-report') }
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
  const cpuAnalysisEnabled = config.cpuAnalysisEnabled === true;
  const deepAnalysisEnabled = config.deepAnalysisEnabled === true;
  const redirectUri = window.location.origin + '/demos/';
  let file = null;
  let localVideoUrl = '';
  let busy = false;
  let abortController = null;
  let activeVideoId = null;
  let downloadedReportUrl = '';

  function clearReport() {
    if (downloadedReportUrl) URL.revokeObjectURL(downloadedReportUrl);
    downloadedReportUrl = '';
    ui.result.hidden = true;
    ui.reportPreview.hidden = true;
    ui.reportFrame.removeAttribute('srcdoc');
    ui.download.removeAttribute('href');
    ui.download.removeAttribute('download');
    ui.download.textContent = 'Download report';
  }

  function feedback(message, tone = '') {
    ui.feedback.textContent = message;
    ui.feedback.dataset.tone = tone;
  }
  function signInFeedback(message, tone = '') {
    ui.authFeedback.textContent = message;
    ui.authFeedback.dataset.tone = tone;
  }
  function oauthFailure(code, description) {
    // OAuth errors are diagnostic text, not trusted markup or a place for tokens.
    const safe = value => typeof value === 'string'
      ? value.replace(/[\u0000-\u001F\u007F]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 240)
      : '';
    return [safe(code), safe(description)].filter(Boolean).join(': ');
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
  function readActiveJobId() {
    try {
      const jobId = sessionStorage.getItem(ACTIVE_JOB_KEY) || '';
      return /^[0-9a-f]{32}$/.test(jobId) ? jobId : '';
    } catch (_) { return ''; }
  }
  function rememberActiveJob(jobId) {
    if (!/^[0-9a-f]{32}$/.test(String(jobId || ''))) return;
    try { sessionStorage.setItem(ACTIVE_JOB_KEY, jobId); } catch (_) {}
  }
  function forgetActiveJob(jobId) {
    if (jobId && readActiveJobId() !== jobId) return;
    try { sessionStorage.removeItem(ACTIVE_JOB_KEY); } catch (_) {}
  }
  function clearAuth() {
    try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
    forgetActiveJob();
    clearReport();
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
    } else if (!cpuAnalysisEnabled) {
      ui.backendStatus.textContent = 'AWS connected — Free Analysis is not yet open';
      ui.backendDetail.textContent = 'Google sign-in and the feedback form are available. Public CPU analysis will open after cost limits and AWS capacity are verified.';
    } else {
      ui.backendStatus.textContent = 'AWS analysis available · limited public beta';
      ui.backendDetail.textContent = 'Up to 5 analysis submissions per day and 50 per month globally, subject to remaining capacity. Each private job runs independently.';
    }
    const tooLarge = file && file.size > limit();
    const ready = backendReady && auth && file && !tooLarge && !busy &&
      (selectedTier === 'free' ? cpuAnalysisEnabled : deepAnalysisEnabled);
    ui.input.disabled = busy;
    ui.clear.disabled = busy;
    ui.run.disabled = !ready;
    ui.run.textContent = busy ? 'Analysis in progress…' : selectedTier === 'paid' ? 'Start Deep Analysis' : 'Start Free Analysis';
    if (tooLarge) {
      ui.helper.textContent = 'The selected video exceeds the ' + formatMB(limit()) + ' per-video limit.';
    } else if (selectedTier === 'paid' && !deepAnalysisEnabled) {
      ui.helper.textContent = 'Deep Analysis credit purchases and GPU processing remain disabled until billing and compute are approved.';
    } else if (selectedTier === 'free' && !cpuAnalysisEnabled) {
      ui.helper.textContent = 'Free Analysis is temporarily closed. The AWS site is public, but processing must pass the cost and capacity checks first.';
    } else if (!backendReady) {
      ui.helper.textContent = 'Local video checks work now. AWS analysis unlocks after the backend and Cognito are provisioned.';
    } else if (!auth) {
      ui.helper.textContent = 'Sign in with Google to upload and start an analysis.';
    } else if (busy) {
      ui.helper.textContent = 'Your upload or analysis is in progress. The stages below show what AWS has confirmed.';
    } else {
      ui.helper.textContent = 'Ready to submit a private ' + selectedTier + ' analysis job.';
    }
  }

  function setFile(nextFile) {
    // Do not replace the file halfway through a multipart upload.
    if (busy) return;
    if (localVideoUrl) URL.revokeObjectURL(localVideoUrl);
    file = nextFile || null;
    clearReport();
    ui.progress.hidden = true;
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
    catch (_) { signInFeedback('Browser storage is required to complete Google sign-in.', 'error'); return; }
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
    if (error) {
      try { sessionStorage.removeItem(PKCE_KEY); } catch (_) {}
      signInFeedback('Google sign-in was rejected: ' + oauthFailure(error, params.get('error_description')), 'error');
      return;
    }
    let pending;
    try { pending = JSON.parse(sessionStorage.getItem(PKCE_KEY) || 'null'); sessionStorage.removeItem(PKCE_KEY); }
    catch (_) { pending = null; }
    if (!pending || !pending.verifier || params.get('state') !== pending.state || Date.now() - pending.createdAt > 600_000) {
      signInFeedback('Sign-in session verification failed. Please retry Google login.', 'error');
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
      if (!response.ok || !result.access_token) {
        throw Error(oauthFailure(result.error, result.error_description) ||
          'Cognito token exchange failed (HTTP ' + response.status + ').');
      }
      sessionStorage.setItem(AUTH_KEY, JSON.stringify({
        accessToken: result.access_token, idToken: result.id_token || '',
        expiresAt: Date.now() + Math.max(0, Number(result.expires_in || 3600) - 60) * 1000
      }));
      signInFeedback('Google sign-in successful.', 'success');
    } catch (error) {
      signInFeedback('Unable to complete Google sign-in: ' +
        (oauthFailure(error && error.message) || 'check the Cognito callback and public client configuration.'), 'error');
    }
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
    if (!response.ok) {
      const error = Error(typeof payload.message === 'string' ? payload.message :
      typeof payload.error?.message === 'string' ? payload.error.message :
        typeof payload.error === 'string' ? payload.error : 'AWS request failed (' + response.status + ').');
      error.code = payload.error?.code || '';
      throw error;
    }
    return payload;
  }

  const stageOrder = ['upload', 'analysis', 'report'];

  function progress(label, percentage, detail = '', stage = 'analysis') {
    ui.progress.hidden = false;
    ui.progressBar.hidden = false;
    ui.status.textContent = label;
    // Percentages apply to transferred upload bytes or a finished report.
    // Batch currently reports states, not frame-level processing progress.
    if (typeof percentage === 'number' && Number.isFinite(percentage)) {
      const value = Math.max(0, Math.min(100, Math.round(percentage)));
      ui.percentage.textContent = value + '%';
      ui.progressBar.value = value;
      ui.progressBar.setAttribute('aria-label', stage === 'upload' ? 'Video upload progress' : 'Report readiness');
    } else {
      ui.percentage.textContent = 'Working…';
      ui.progressBar.removeAttribute('value');
      ui.progressBar.setAttribute('aria-label', 'AWS job active; exact progress is unavailable');
    }
    ui.detail.textContent = detail;
    const stageIndex = stage === 'complete' ? stageOrder.length : stageOrder.indexOf(stage);
    stageOrder.forEach((name, index) => {
      const marker = ui.stages[name];
      marker.classList.toggle('is-complete', index < stageIndex);
      marker.classList.toggle('is-current', index === stageIndex);
      if (index === stageIndex) marker.setAttribute('aria-current', 'step');
      else marker.removeAttribute('aria-current');
    });
  }

  function stopProgress(label, detail, stage = 'analysis') {
    progress(label, null, detail, stage);
    ui.progressBar.hidden = true;
    ui.percentage.textContent = 'Stopped';
  }

  async function uploadMultipart(upload, signal, sourceFile) {
    const partSize = Number(upload.part_size_bytes);
    const partCount = Number(upload.part_count);
    if (!Number.isSafeInteger(partSize) || partSize < 5 * 1024 * 1024 ||
        !Number.isSafeInteger(partCount) || partCount < 1 || partCount > 10000 ||
        partCount !== Math.ceil(sourceFile.size / partSize)) {
      throw Error('The AWS backend returned invalid multipart upload configuration.');
    }
    const parts = [];
    let nextPart = 1;
    let uploadedBytes = 0;
    progress('Uploading to private storage', 0, '0 of ' + partCount + ' parts uploaded.', 'upload');
    async function worker() {
      while (nextPart <= partCount) {
        const partNumber = nextPart++;
        const signed = await api('/uploads/part', {
          method: 'POST', body: { video_id: upload.video_id, part_number: partNumber }, signal
        });
        const target = new URL(signed.url);
        if (target.protocol !== 'https:') throw Error('The upload URL is not secure.');
        const start = (partNumber - 1) * partSize;
        const end = Math.min(partNumber * partSize, sourceFile.size);
        const response = await fetch(target.toString(), {
          method: 'PUT', body: sourceFile.slice(start, end), signal
        });
        if (!response.ok) throw Error('An S3 upload part failed (' + response.status + ').');
        const etag = response.headers.get('ETag');
        if (!etag) throw Error('S3 upload response did not expose ETag. Check bucket CORS.');
        parts.push({ part_number: partNumber, etag });
        uploadedBytes += end - start;
        progress('Uploading to private storage', uploadedBytes / sourceFile.size * 100,
          parts.length + ' of ' + partCount + ' parts uploaded.', 'upload');
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, partCount) }, worker));
    return parts.sort((a, b) => a.part_number - b.part_number);
  }

  async function waitForAnalysis(jobId, signal, { autoDownload = true } = {}) {
    // A Fargate job can run for an hour; queueing and cold start add time.
    // Keep the most recent successful job ID as well, so the owner can reopen
    // the report after a refresh while it remains within its retention window.
    const deadline = Date.now() + 90 * 60 * 1000;
    while (Date.now() < deadline) {
      if (signal.aborted) throw Error('Upload cancelled.');
      const job = await api('/analysis/jobs/' + encodeURIComponent(jobId), { signal });
      const state = String(job.status || '').toLowerCase();
      if (['completed', 'succeeded', 'finished'].includes(state)) {
        progress('Preparing your report', null, 'AWS completed the analysis. Retrieving your private report.', 'report');
        const report = await api('/reports/' + encodeURIComponent(jobId), { signal });
        if (!report.download_url || new URL(report.download_url).protocol !== 'https:') {
          throw Error('The report is complete but a secure download URL is unavailable.');
        }
        ui.download.href = report.download_url;
        ui.download.textContent = 'Download report data (JSON)';
        ui.result.hidden = false;
        // S3 links are short-lived, but a successful download is available
        // even if this optional browser preview fails. The sandbox allows no
        // scripts, forms, navigation or same-origin privileges.
        try {
          const response = await fetch(report.download_url, {
            method: 'GET', credentials: 'omit', cache: 'no-store', signal
          });
          const declaredLength = Number(response.headers.get('Content-Length') || 0);
          if (!response.ok || declaredLength > 32 * 1024 * 1024) throw Error('preview_unavailable');
          const document = await response.json();
          if (document.schema_version !== 'strokesense-free-report-v1' ||
              document.job_id !== jobId || typeof document.report_html !== 'string' ||
              document.report_html.length > 24 * 1024 * 1024) throw Error('preview_unavailable');
          ui.reportFrame.srcdoc = document.report_html;
          ui.reportPreview.hidden = false;
          downloadedReportUrl = URL.createObjectURL(new Blob([document.report_html], {
            type: 'text/html;charset=utf-8'
          }));
          ui.download.href = downloadedReportUrl;
          ui.download.download = 'strokesense-report-' + jobId + '.html';
          ui.download.textContent = 'Download HTML report';
          // Browser download policies differ; the visible link always remains.
          if (autoDownload) ui.download.click();
        } catch (_) {
          ui.reportPreview.hidden = true;
          ui.reportFrame.removeAttribute('srcdoc');
        }
        feedback('Your report is ready. Keep the downloaded HTML file; the online copy expires in 3 days.', 'success');
        progress('Report ready', 100, 'Your analysis is complete. You can view or download your report below.', 'complete');
        return;
      }
      if (['failed', 'cancelled', 'error'].includes(state)) {
        forgetActiveJob(jobId);
        throw Error('Analysis ' + state + '. Your reserved allowance will be returned by the backend.');
      }
      // The status endpoint does not expose measured frame/processing progress.
      // Show the actual Batch lifecycle, with an indeterminate progress bar.
      const stages = {
        submitted: ['Job submitted', 'AWS accepted your analysis. Waiting for it to enter the processing queue.'],
        pending: ['Waiting for AWS', 'AWS is scheduling your private analysis job.'],
        runnable: ['Queued for processing', 'Waiting for available AWS CPU capacity.'],
        starting: ['Starting AWS worker', 'An analysis container is starting and loading the model.'],
        running: ['Processing video on AWS', 'Your video is being processed. This may take several minutes; an exact percentage is not available.']
      };
      const [label, detail] = stages[state] || ['Checking AWS job', 'Waiting for the latest status from AWS Batch.'];
      progress(label, null, detail + ' Status: ' + (state || 'unknown') + '. Checking every 5 seconds.', 'analysis');
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, 5000);
        signal.addEventListener('abort', () => { clearTimeout(timer); reject(Error('Cancelled.')); }, { once: true });
      });
    }
    throw Error('Analysis is still pending. Refresh this tab later to resume checking your private job.');
  }

  async function startAnalysis() {
    if (busy || !backendReady || !readAuth() || !file || file.size > limit()) return;
    if (tier() === 'free' && !cpuAnalysisEnabled) return;
    if (tier() === 'paid' && !deepAnalysisEnabled) return;
    busy = true;
    activeVideoId = null;
    let jobSubmitted = false;
    abortController = new AbortController();
    clearReport();
    feedback('');
    ui.cancel.hidden = false;
    render();
    try {
      progress('Preparing secure upload', null, 'Checking your allowance and reserving private S3 storage.', 'upload');
      const sourceFile = file;
      const upload = await api('/uploads/start', {
        method: 'POST', body: {
          filename: sourceFile.name, content_type: sourceFile.type || 'application/octet-stream',
          size_bytes: sourceFile.size, tier: tier()
        }, signal: abortController.signal
      });
      activeVideoId = upload.video_id;
      const parts = await uploadMultipart(upload, abortController.signal, sourceFile);
      progress('Verifying uploaded video', null, 'All parts transferred. Confirming your file in private S3 storage.', 'upload');
      await api('/uploads/complete', {
        method: 'POST', body: { video_id: upload.video_id, parts }, signal: abortController.signal
      });
      feedback('Video uploaded privately. Submitting it to AWS for analysis…', 'success');
      progress('Submitting analysis', null, 'Scheduling an independent AWS processing job.', 'analysis');
      const job = await api('/analysis/jobs', {
        method: 'POST', body: { video_id: upload.video_id }, signal: abortController.signal
      });
      jobSubmitted = true;
      rememberActiveJob(job.job_id);
      activeVideoId = null;
      ui.cancel.hidden = true;
      feedback('Video uploaded. Your private AWS analysis job is underway.', 'success');
      await waitForAnalysis(job.job_id, abortController.signal);
    } catch (error) {
      // A timeout after Batch submission may still have launched the worker.
      // Preserve this video ID for ownership-scoped status checks, not a retry.
      if (error?.code === 'submission_uncertain' && activeVideoId) {
        rememberActiveJob(activeVideoId);
        jobSubmitted = true;
      }
      // Once a job was submitted, only its server-side lifecycle can refund it.
      if (activeVideoId && !jobSubmitted) {
        try { await api('/uploads/abort', { method: 'POST', body: { video_id: activeVideoId } }); }
        catch (_) { /* The backend also reclaims abandoned reservations. */ }
      }
      feedback(error && error.message ? error.message : 'The upload could not be completed.', 'error');
      stopProgress(jobSubmitted ? 'Status check paused' : 'Unable to start analysis',
        jobSubmitted ? 'Refresh this tab later to resume checking the same private job.' : 'No analysis was started.',
        jobSubmitted ? 'analysis' : 'upload');
    } finally {
      busy = false;
      activeVideoId = null;
      abortController = null;
      ui.cancel.hidden = true;
      render();
    }
  }

  async function resumeAnalysis() {
    const jobId = readActiveJobId();
    if (!jobId || !readAuth() || !backendReady || busy) return;
    busy = true;
    abortController = new AbortController();
    ui.cancel.hidden = true;
    clearReport();
    render();
    progress('Checking saved AWS job', null, 'Resuming private job ' + jobId.slice(0, 8) + '…', 'analysis');
    try {
      await waitForAnalysis(jobId, abortController.signal, { autoDownload: false });
    } catch (error) {
      feedback(error && error.message ? error.message : 'Could not check the saved job.', 'error');
      stopProgress('Status check paused', 'Refresh this tab later to check the same private job.', 'analysis');
    } finally {
      busy = false;
      abortController = null;
      render();
    }
  }

  ui.login.addEventListener('click', signIn);
  ui.logout.addEventListener('click', () => { clearAuth(); signInFeedback('Signed out of this preview.'); render(); });
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
  finishSignIn().then(resumeAnalysis);
})();
