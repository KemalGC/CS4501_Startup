/* A small owner-only history on the analyzer page. Full history lives at /library/. */
(() => {
  'use strict';

  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const JOB_ID = /^[a-f0-9]{32}$/;
  const BUCKET = 'strokesense-aws-dev-851226124502-us-east-1';
  const $ = id => document.getElementById(id);
  const ui = {
    list: $('recent-analyses-list'),
    notice: $('recent-analyses-notice'),
    refresh: $('recent-analyses-refresh')
  };
  if (!ui.list || !ui.notice || !ui.refresh) return;

  let apiBase = '';
  try {
    const url = new URL(window.STROKESENSE_AWS_CONFIG?.apiBaseUrl);
    if (url.protocol === 'https:') apiBase = url.origin;
  } catch (_) { /* Report a configuration issue in the panel. */ }

  let serverJobs = [];
  const submittedJobs = new Map();
  let loading = false;
  let refreshQueued = false;

  function readAuth() {
    try {
      const auth = JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null');
      return auth && typeof auth.accessToken === 'string' && auth.accessToken &&
        Number(auth.expiresAt) > Date.now() + 15_000 ? auth : null;
    } catch (_) { return null; }
  }

  function item(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  }

  function filename(value) {
    return typeof value === 'string' && value.trim()
      ? value.split(/[\\/]/).pop().slice(0, 150) || 'Rowing video'
      : 'Rowing video';
  }

  function timeDate(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = typeof value === 'number' ? value * 1000 : NaN;
    const date = new Date(Number.isFinite(numeric) ? numeric : value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function displayDate(value) {
    const date = timeDate(value);
    return date ? date.toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'
    }) : 'Not recorded';
  }

  function reportAvailable(job) {
    if (String(job.status || '').toLowerCase() !== 'succeeded') return false;
    if (typeof job.report_available === 'boolean') return job.report_available;
    const expiry = timeDate(job.report_expires_at);
    return Boolean(expiry && expiry.getTime() > Date.now());
  }

  function badgeStatus(job) {
    const status = String(job.status || '').toLowerCase();
    if (status === 'succeeded') return reportAvailable(job) ? ['Report ready', 'ready'] : ['Report expired', 'muted'];
    if (['submitted', 'pending', 'runnable', 'starting', 'running', 'submitting', 'uploading', 'uploaded'].includes(status)) {
      return ['Processing', 'progress'];
    }
    if (status === 'failed') return ['Failed', 'muted'];
    return ['Unavailable', 'muted'];
  }

  function notice(message, tone = '') {
    ui.notice.textContent = message;
    ui.notice.dataset.tone = tone;
  }

  function safeReportUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.hash ||
          !url.pathname.startsWith('/reports/free/') || !url.searchParams.get('X-Amz-Signature')) return null;
      return [
        BUCKET + '.s3.us-east-1.amazonaws.com',
        BUCKET + '.s3.amazonaws.com'
      ].includes(url.hostname.toLowerCase()) ? url : null;
    } catch (_) { return null; }
  }

  async function previewReport(job, frame, label, disclosure, controller) {
    const auth = readAuth();
    if (!auth || !apiBase) {
      label.textContent = 'Sign in again to open this private report.';
      return;
    }
    const timeout = setTimeout(() => controller.abort(), 15000);
    label.textContent = 'Loading your private report…';
    try {
      const result = await fetch(apiBase + '/reports/' + encodeURIComponent(job.job_id), {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (!result.ok) throw Error(result.status === 410 || result.status === 404
        ? 'This report has expired or is unavailable.' : 'Report access was not granted.');
      const payload = await result.json();
      const signedUrl = safeReportUrl(payload?.download_url);
      if (!signedUrl) throw Error('The report service did not return a valid private link.');
      const response = await fetch(signedUrl.toString(), {
        method: 'GET', credentials: 'omit', cache: 'no-store', signal: controller.signal
      });
      const declaredLength = Number(response.headers?.get('Content-Length') || 0);
      if (!response.ok || declaredLength > 32 * 1024 * 1024) throw Error('Report preview is unavailable.');
      const report = await response.json();
      if (report?.job_id !== job.job_id || report?.schema_version !== 'strokesense-free-report-v1' ||
          typeof report.report_html !== 'string' || report.report_html.length > 24 * 1024 * 1024) {
        throw Error('Report data did not pass validation.');
      }
      if (!disclosure.open || controller.signal.aborted) return;
      // The coaching report is third-party-like HTML: never interpolate it into
      // the parent DOM or grant it scripts, navigation, forms or same-origin.
      window.StrokeSenseAutoReportFrame?.attach(frame);
      frame.srcdoc = report.report_html;
      frame.hidden = false;
      label.textContent = 'Your previous coaching report is shown below.';
    } catch (error) {
      if (!disclosure.open || controller.signal.aborted) return;
      label.textContent = error && error.message ? error.message : 'Unable to reopen this report.';
    } finally {
      clearTimeout(timeout);
    }
  }

  function historyCard(job, expanded) {
    const disclosure = item('details', 'aws-history-entry');
    disclosure.dataset.jobId = job.job_id;
    const summary = item('summary', 'aws-history-summary');
    const title = item('span', 'aws-history-summary-title');
    title.appendChild(item('strong', '', filename(job.filename)));
    title.appendChild(item('span', '', displayDate(job.created_at)));
    const [state, tone] = badgeStatus(job);
    const badge = item('span', 'aws-history-state', state);
    badge.dataset.tone = tone;
    summary.appendChild(title);
    summary.appendChild(badge);
    disclosure.appendChild(summary);

    const content = item('div', 'aws-history-content');
    const meta = item('p', 'aws-history-meta');
    const parts = ['Uploaded ' + displayDate(job.created_at)];
    if (job.completed_at) parts.push('Completed ' + displayDate(job.completed_at));
    if (typeof job.analysis_wall_ms === 'number' && job.analysis_wall_ms >= 0) {
      parts.push('Processing ' + Math.round(job.analysis_wall_ms / 1000) + ' sec');
    }
    if (job.report_expires_at) parts.push('Report expires ' + displayDate(job.report_expires_at));
    meta.textContent = parts.join(' · ');
    content.appendChild(meta);

    const actions = item('div', 'aws-history-actions');
    const available = reportAvailable(job);
    const status = String(job.status || '').toLowerCase();
    if (available) {
      const report = item('a', 'aws-button aws-button-outline', 'Open full report');
      report.href = '/demos/?job=' + encodeURIComponent(job.job_id);
      actions.appendChild(report);
      const video = item('a', 'aws-button aws-button-outline', 'Open annotated video');
      video.href = '/library/?video=' + encodeURIComponent(job.job_id);
      actions.appendChild(video);
    } else if (['submitted', 'pending', 'runnable', 'starting', 'running', 'submitting'].includes(status)) {
      const progress = item('a', 'aws-button aws-button-outline', 'Check progress');
      progress.href = '/demos/?job=' + encodeURIComponent(job.job_id);
      actions.appendChild(progress);
    } else {
      actions.appendChild(item('span', 'aws-history-meta', 'This online report is no longer available.'));
    }
    content.appendChild(actions);

    if (available) {
      const label = item('p', 'aws-history-preview-note', 'Expand to preview the previous coaching report.');
      const frame = item('iframe', 'aws-history-report-frame');
      frame.title = 'Previous private StrokeSense report for ' + filename(job.filename);
      frame.setAttribute('sandbox', 'allow-same-origin');
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.setAttribute('loading', 'lazy');
      frame.setAttribute('scrolling', 'no');
      frame.hidden = true;
      content.appendChild(label);
      content.appendChild(frame);
      let controller = null;
      disclosure.addEventListener('toggle', () => {
        if (controller) controller.abort();
        controller = null;
        frame.removeAttribute('srcdoc');
        frame.hidden = true;
        if (!disclosure.open) return;
        controller = new AbortController();
        void previewReport(job, frame, label, disclosure, controller);
      });
      if (expanded) disclosure.open = true;
    }
    disclosure.appendChild(content);
    return disclosure;
  }

  function renderList() {
    const expanded = new Set();
    for (const card of ui.list.children) {
      if (card.open && card.dataset?.jobId) expanded.add(card.dataset.jobId);
    }
    const merged = new Map();
    for (const job of serverJobs) merged.set(job.job_id, job);
    for (const [jobId, job] of submittedJobs) merged.set(jobId, { ...merged.get(jobId), ...job });
    const jobs = [...merged.values()].sort((a, b) =>
      (timeDate(b.created_at)?.getTime() || 0) - (timeDate(a.created_at)?.getTime() || 0)).slice(0, 8);
    ui.list.replaceChildren(...jobs.map(job => historyCard(job, expanded.has(job.job_id))));
    ui.list.hidden = jobs.length === 0;
    notice(jobs.length ? 'Your latest ' + jobs.length + ' analysis sessions. Expand any row to review it.'
      : 'No analyses yet. Your submitted videos will appear here automatically.');
  }

  function signedOut() {
    serverJobs = [];
    submittedJobs.clear();
    ui.list.replaceChildren();
    ui.list.hidden = true;
    notice('Sign in with Google to view your private analysis history.');
  }

  async function refresh() {
    if (loading) { refreshQueued = true; return; }
    const auth = readAuth();
    if (!auth) { signedOut(); return; }
    if (!apiBase) { notice('The private history service is not configured.', 'error'); return; }
    loading = true;
    ui.refresh.disabled = true;
    notice('Loading your private analysis history…');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/analysis/jobs?limit=12', {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (response.status === 401) { signedOut(); return; }
      if (!response.ok) throw Error('Your previous analyses are temporarily unavailable.');
      const data = await response.json();
      if (!data || !Array.isArray(data.jobs)) throw Error('History returned an unexpected response.');
      if (!readAuth() || readAuth().accessToken !== auth.accessToken) { signedOut(); return; }
      serverJobs = data.jobs.filter(job => job && JOB_ID.test(job.job_id));
      for (const job of serverJobs) {
        const optimistic = submittedJobs.get(job.job_id);
        if (!optimistic || job.status === 'succeeded' || job.status === 'failed') {
          submittedJobs.delete(job.job_id);
        }
      }
      renderList();
    } catch (error) {
      renderList();
      if (readAuth()) notice(error && error.name === 'AbortError'
        ? 'History request timed out. Refresh to try again.'
        : 'Could not load history. Your latest submitted job will remain shown here.', 'error');
    } finally {
      clearTimeout(timeout);
      loading = false;
      ui.refresh.disabled = false;
      if (refreshQueued) { refreshQueued = false; void refresh(); }
    }
  }

  function notifySubmitted(jobId, videoName, state = 'submitted') {
    if (!JOB_ID.test(String(jobId || '')) || !readAuth()) return;
    submittedJobs.set(jobId, {
      job_id: jobId, filename: videoName, status: state === 'uploading' ? 'uploading' : 'submitted',
      created_at: submittedJobs.get(jobId)?.created_at || Date.now() / 1000
    });
    renderList();
    void refresh();
  }

  function notifyAborted(jobId) {
    submittedJobs.delete(jobId);
    renderList();
    void refresh();
  }

  function notifyCompleted(jobId) {
    if (!JOB_ID.test(String(jobId || '')) || !readAuth()) return;
    const previous = submittedJobs.get(jobId) || { job_id: jobId, created_at: Date.now() / 1000 };
    submittedJobs.set(jobId, { ...previous, status: 'succeeded', report_available: true });
    renderList();
    void refresh();
  }

  ui.refresh.addEventListener('click', () => void refresh());
  window.StrokeSenseRecentAnalyses = { refresh, signedOut, notifySubmitted, notifyCompleted, notifyAborted };
  void refresh();
})();
