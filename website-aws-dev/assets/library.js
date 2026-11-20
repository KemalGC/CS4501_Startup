/* Private AWS history. The API, not this page, enforces Cognito ownership. */
(function () {
  'use strict';

  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const JOB_ID = /^[a-f0-9]{32}$/;
  const MEDIA_BUCKET = 'strokesense-aws-dev-851226124502-us-east-1';
  const config = window.STROKESENSE_AWS_CONFIG || {};
  const $ = id => document.getElementById(id);
  const ui = {
    account: $('library-account'), signIn: $('library-sign-in'),
    refresh: $('library-refresh'), notice: $('library-notice'),
    list: $('library-list'), more: $('library-more'),
    videoPanel: $('library-video-panel'), video: $('library-video-player'),
    videoLink: $('library-video-link'),
    videoTitle: $('library-video-title'), videoNotice: $('library-video-notice'),
    closeVideo: $('library-close-video'), refreshVideo: $('library-refresh-video')
  };
  if (Object.values(ui).some(element => !element)) return;

  let apiBase = '';
  try {
    const url = new URL(config.apiBaseUrl);
    if (url.protocol === 'https:') apiBase = url.origin;
  } catch (_) { /* Show a clear configuration message instead of fetching. */ }

  let nextCursor = null;
  let loading = false;
  let itemCount = 0;
  let viewing = false;
  let viewerGeneration = 0;
  let activeVideoJob = null;
  let videoLinkExpiryTimer = null;
  let requestedVideoId = '';
  try {
    const requested = new URLSearchParams(window.location?.search || '').get('video');
    if (requested && JOB_ID.test(requested)) requestedVideoId = requested;
  } catch (_) { /* Ignore invalid deep links. */ }
  const renderedIds = new Set();

  function readAuth() {
    try {
      const auth = JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null');
      if (auth && typeof auth.accessToken === 'string' && auth.accessToken &&
          Number(auth.expiresAt) > Date.now() + 15_000) return auth;
    } catch (_) { /* Malformed or inaccessible session storage. */ }
    return null;
  }

  function accountLabel(auth) {
    if (!auth || !auth.idToken) return 'Signed in with Google';
    try {
      const encoded = auth.idToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const claims = JSON.parse(atob(encoded));
      if (typeof claims.email === 'string' && claims.email.length < 255) {
        return 'Signed in as ' + claims.email;
      }
    } catch (_) { /* An absent email does not affect access control. */ }
    return 'Signed in with Google';
  }

  function setNotice(message, tone = '') {
    ui.notice.textContent = message;
    ui.notice.dataset.tone = tone;
  }

  function timeDate(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = typeof value === 'number' ? value * 1000 : NaN;
    const date = new Date(Number.isFinite(numeric) ? numeric : value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function displayDate(value) {
    const date = timeDate(value);
    if (!date) return 'Not recorded';
    return date.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    });
  }

  function elapsedSeconds(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
    const whole = Math.round(value);
    const minutes = Math.floor(whole / 60);
    const seconds = String(whole % 60).padStart(2, '0');
    return minutes ? `${minutes}:${seconds}` : `${whole} sec`;
  }

  function displayFilename(value) {
    if (typeof value !== 'string' || !value.trim()) return 'Rowing video';
    const shortName = value.split(/[\\/]/).pop().trim();
    return shortName.slice(0, 150) || 'Rowing video';
  }

  function reportAvailable(job) {
    if (typeof job.report_available === 'boolean') return job.report_available;
    const expiry = timeDate(job.report_expires_at);
    return String(job.status).toLowerCase() === 'succeeded' && Boolean(expiry && expiry.getTime() > Date.now());
  }

  function statusInfo(job) {
    const status = String(job.status || '').toLowerCase();
    if (status === 'succeeded') {
      return reportAvailable(job)
        ? { label: 'Report ready', tone: 'ready' }
        : { label: 'Report unavailable', tone: 'muted' };
    }
    if (['submitted', 'pending', 'runnable', 'starting', 'running', 'submitting'].includes(status)) {
      return { label: 'In progress', tone: 'progress' };
    }
    if (status === 'uploaded') return { label: 'Upload received', tone: 'progress' };
    if (status === 'uploading') return { label: 'Uploading', tone: 'progress' };
    if (status === 'failed') return { label: 'Analysis failed', tone: 'muted' };
    if (status === 'aborted' || status === 'cancelled') return { label: 'Cancelled', tone: 'muted' };
    return { label: 'Status unavailable', tone: 'muted' };
  }

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  }

  function field(label, value) {
    const wrapper = node('div', 'library-field');
    wrapper.appendChild(node('dt', '', label));
    wrapper.appendChild(node('dd', '', value));
    return wrapper;
  }

  function validVideoUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.hash ||
          !url.searchParams.get('X-Amz-Signature') || ![
            MEDIA_BUCKET + '.s3.us-east-1.amazonaws.com',
            MEDIA_BUCKET + '.s3.amazonaws.com'
          ].includes(url.hostname.toLowerCase())) return null;
      return url;
    } catch (_) { return null; }
  }

  function clearVideo() {
    viewerGeneration += 1;
    activeVideoJob = null;
    if (videoLinkExpiryTimer !== null) clearTimeout(videoLinkExpiryTimer);
    videoLinkExpiryTimer = null;
    if (typeof ui.video.pause === 'function') ui.video.pause();
    ui.video.removeAttribute('src');
    if (typeof ui.video.load === 'function') ui.video.load();
    ui.videoLink.removeAttribute('href');
    ui.videoLink.hidden = true;
    ui.videoPanel.hidden = true;
    ui.refreshVideo.disabled = false;
  }

  async function watchAnnotatedVideo(job) {
    if (viewing || !job || !JOB_ID.test(job.job_id) || !reportAvailable(job) ||
        String(job.status || '').toLowerCase() !== 'succeeded') return;
    const auth = readAuth();
    if (!auth) { signedOut('Your sign-in expired. Sign in again to watch your annotated video.'); return; }
    if (!apiBase) { setNotice('AWS API is not configured.', 'error'); return; }
    viewing = true;
    clearVideo();
    const generation = viewerGeneration;
    activeVideoJob = job;
    ui.videoPanel.hidden = false;
    ui.videoTitle.textContent = 'Annotated video · ' + displayFilename(job.filename);
    ui.refreshVideo.disabled = true;
    ui.videoNotice.textContent = 'Requesting temporary access to your annotated video…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/reports/' + encodeURIComponent(job.job_id) + '/artifacts', {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (generation !== viewerGeneration) return;
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Your sign-in expired. Sign in again to watch your annotated video.');
        return;
      }
      if (response.status === 403 || response.status === 404 || response.status === 410) {
        clearVideo();
        setNotice('The annotated video is unavailable, expired, or not authorized for this account.', 'error');
        return;
      }
      if (!response.ok) throw Error('The annotated video could not be loaded.');
      const data = await response.json();
      if (generation !== viewerGeneration) return;
      if (!data || data.job_id !== job.job_id || !data.video_url) {
        clearVideo();
        setNotice('No annotated video was saved for this analysis. The written report may still be available.', 'error');
        return;
      }
      const videoUrl = validVideoUrl(data.video_url);
      if (!videoUrl) throw Error('The video service returned an invalid secure media link.');
      // This owner-authorized presigned URL is kept only in the player and
      // temporary open link; it is never stored or displayed as text.
      ui.video.src = videoUrl.toString();
      if (typeof ui.video.load === 'function') ui.video.load();
      const seconds = Number.isFinite(Number(data.expires_in))
        ? Math.min(900, Math.max(1, Math.round(Number(data.expires_in)))) : 60;
      ui.videoLink.href = videoUrl.toString();
      ui.videoLink.hidden = false;
      videoLinkExpiryTimer = setTimeout(() => {
        if (generation !== viewerGeneration) return;
        ui.videoLink.removeAttribute('href');
        ui.videoLink.hidden = true;
        ui.videoNotice.textContent = 'This video link has expired. Refresh temporary video access to open it again.';
        videoLinkExpiryTimer = null;
      }, seconds * 1000);
      ui.videoNotice.textContent = `Annotated video link lasts up to ${seconds} seconds. Refresh video access if seeking stops.`;
    } catch (error) {
      if (generation !== viewerGeneration) return;
      clearVideo();
      setNotice(error && error.name === 'AbortError' ? 'Video access timed out. Please try again.'
        : 'Unable to open annotated video. Please try again later.', 'error');
    } finally {
      clearTimeout(timeout);
      viewing = false;
      ui.refreshVideo.disabled = false;
    }
  }

  async function revokeConsent(job, button, note) {
    const auth = readAuth();
    if (!auth) { signedOut('Your session expired. Sign in again to manage review access.'); return; }
    if (!apiBase || loading || button.disabled || !JOB_ID.test(job.job_id)) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Revoking access…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/analysis/jobs/' + encodeURIComponent(job.job_id) + '/review', {
        method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken, 'Content-Type': 'application/json' },
        body: JSON.stringify({ allow_admin_review: false }),
        signal: controller.signal
      });
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Your session expired. Sign in again to manage review access.');
        return;
      }
      if (!response.ok) throw Error('Could not revoke review access. Please try again.');
      job.allow_admin_review = false;
      button.hidden = true;
      note.textContent = 'Staff review access revoked. New links are blocked; existing links may work for up to 60 seconds.';
      setNotice('Review access revoked for ' + displayFilename(job.filename) + '.', 'success');
    } catch (error) {
      setNotice(error && error.name === 'AbortError'
        ? 'The review permission request timed out. Refresh the history to confirm its current state.'
        : 'Unable to revoke review permission. Please try again later.', 'error');
    } finally {
      clearTimeout(timeout);
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }

  async function deleteAnalysis(job, button) {
    if (!job || !JOB_ID.test(job.job_id) || loading || button.disabled) return;
    const status = String(job.status || '').toLowerCase();
    if (!['succeeded', 'failed', 'aborted'].includes(status)) return;
    if (!window.confirm(
      'Permanently delete "' + displayFilename(job.filename) + '"? This removes the original upload, annotated video, coaching report, and library entry. It also unpublishes any shared copy. This cannot be undone, and completed analyses still count toward your lifetime free allowance. Previously downloaded copies cannot be recalled.'
    )) return;
    const auth = readAuth();
    if (!auth) { signedOut('Please sign in again to delete this analysis.'); return; }
    if (!apiBase) { setNotice('AWS API is not configured.', 'error'); return; }
    button.disabled = true;
    button.textContent = 'Deleting…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/analysis/jobs/' + encodeURIComponent(job.job_id) + '/delete', {
        method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Your sign-in expired. Sign in again to manage your library.');
        return;
      }
      if (response.status === 404) {
        await loadHistory(true);
        setNotice('This analysis is already gone from your library.', 'success');
        return;
      }
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw Error(error?.error?.message || 'Unable to delete this analysis.');
      }
      const result = await response.json();
      if (!result || result.job_id !== job.job_id ||
          !['deleted', 'deleting'].includes(result.status)) {
        throw Error('The deletion service returned an unexpected response.');
      }
      if (activeVideoJob?.job_id === job.job_id) clearVideo();
      await loadHistory(true);
      setNotice(result.status === 'deleted'
        ? 'Analysis deleted. The original upload, report, and annotated video have been removed.'
        : 'Analysis removed from the library. AWS is finishing media cleanup.', 'success');
    } catch (error) {
      setNotice(error && error.name === 'AbortError'
        ? 'Deletion timed out. Refresh your library to verify whether it was removed.'
        : (error?.message || 'Deletion could not be confirmed. Refresh your library.'), 'error');
    } finally {
      clearTimeout(timeout);
      button.disabled = false;
      button.textContent = 'Delete analysis';
    }
  }

  function jobCard(job) {
    const status = statusInfo(job);
    const card = node('article', 'library-card');
    const top = node('div', 'library-card-top');
    const heading = node('div');
    heading.appendChild(node('span', 'library-card-eyebrow', 'Rowing analysis'));
    heading.appendChild(node('h3', '', displayFilename(job.filename)));
    const badge = node('span', 'library-badge', status.label);
    badge.dataset.tone = status.tone;
    top.appendChild(heading);
    top.appendChild(badge);
    card.appendChild(top);

    const details = node('dl', 'library-fields');
    details.appendChild(field('Uploaded', displayDate(job.created_at)));
    if (job.completed_at) details.appendChild(field('Completed', displayDate(job.completed_at)));
    const clipDuration = elapsedSeconds(job.duration_seconds);
    if (clipDuration) details.appendChild(field('Clip length', clipDuration));
    if (typeof job.analysis_wall_ms === 'number') {
      const runDuration = elapsedSeconds(job.analysis_wall_ms / 1000);
      if (runDuration) details.appendChild(field('Analysis time', runDuration));
    }
    if (job.report_expires_at) {
      details.appendChild(field('Report expires', displayDate(job.report_expires_at)));
    }
    card.appendChild(details);

    const actions = node('div', 'library-card-actions');
    const state = String(job.status || '').toLowerCase();
    const canOpen = state === 'succeeded' ? reportAvailable(job)
      : ['submitted', 'pending', 'runnable', 'starting', 'running', 'submitting'].includes(state);
    if (canOpen) {
      const link = node('a', 'pill pill-coral', state === 'succeeded' ? 'Open report' : 'Check progress');
      link.href = '/demos/?job=' + encodeURIComponent(job.job_id);
      actions.appendChild(link);
      if (state === 'succeeded') {
        const watch = node('button', 'library-watch-video', 'Watch annotated video');
        watch.type = 'button';
        watch.addEventListener('click', () => watchAnnotatedVideo(job));
        actions.appendChild(watch);
      }
    } else {
      actions.appendChild(node('span', 'library-action-note',
        state === 'succeeded'
          ? 'The report may have expired or been removed. Your history remains here.'
          : 'No available report for this analysis.'));
    }
    if (job.video_available === false) {
      actions.appendChild(node('span', 'library-action-note', 'Original video no longer available.'));
    }
    if (job.allow_admin_review === true) {
      const note = node('span', 'library-action-note',
        'Staff review allowed. Revoking blocks new links; existing links may work for 60 seconds, and saved copies cannot be recalled.');
      const button = node('button', 'library-review-revoke', 'Revoke staff access');
      button.type = 'button';
      button.addEventListener('click', () => revokeConsent(job, button, note));
      actions.appendChild(note);
      actions.appendChild(button);
    }
    if (['succeeded', 'failed', 'aborted'].includes(state)) {
      const erase = node('button', 'library-delete-button', 'Delete analysis');
      erase.type = 'button';
      erase.addEventListener('click', () => deleteAnalysis(job, erase));
      actions.appendChild(erase);
    }
    card.appendChild(actions);
    return card;
  }

  function clearCards() {
    nextCursor = null;
    itemCount = 0;
    renderedIds.clear();
    ui.list.replaceChildren();
    ui.list.hidden = true;
  }

  function signedOut(message) {
    clearCards();
    clearVideo();
    ui.account.textContent = 'Not signed in';
    ui.signIn.hidden = false;
    ui.refresh.hidden = true;
    ui.more.hidden = true;
    setNotice(message || 'Sign in with Google to open your private analysis library.');
  }

  async function loadHistory(reset = false) {
    if (loading) return;
    const auth = readAuth();
    if (!auth) { signedOut(); return; }
    ui.account.textContent = accountLabel(auth);
    ui.signIn.hidden = true;
    ui.refresh.hidden = false;
    if (!apiBase) {
      setNotice('Your analysis history is temporarily unavailable because the AWS API is not configured.', 'error');
      return;
    }

    if (reset) {
      clearCards();
      clearVideo();
    }
    loading = true;
    ui.more.disabled = true;
    ui.refresh.disabled = true;
    setNotice('Loading your private analyses…');

    const url = new URL(apiBase + '/analysis/jobs');
    url.searchParams.set('limit', '20');
    if (nextCursor) url.searchParams.set('cursor', nextCursor);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.toString(), {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken },
        signal: controller.signal
      });
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Your sign-in has expired. Sign in with Google again to see your analyses.');
        return;
      }
      if (response.status === 403) {
        clearCards();
        clearVideo();
        ui.more.hidden = true;
        setNotice('This account is not authorized to access the analysis history.', 'error');
        return;
      }
      if (response.status === 404) {
        setNotice('My Analyses is being rolled out. Your existing reports remain accessible through the analyzer while this feature is configured.', 'error');
        ui.more.hidden = true;
        return;
      }
      if (!response.ok) throw Error('The analysis list could not be loaded. Please try again later.');
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.jobs)) throw Error('The analysis service returned an unexpected response.');

      for (const job of payload.jobs) {
        if (!job || typeof job.job_id !== 'string' || !JOB_ID.test(job.job_id) || renderedIds.has(job.job_id)) continue;
        renderedIds.add(job.job_id);
        ui.list.appendChild(jobCard(job));
        itemCount += 1;
        if (requestedVideoId === job.job_id && reportAvailable(job)) {
          requestedVideoId = '';
          void watchAnnotatedVideo(job);
        }
      }
      nextCursor = typeof payload.next_cursor === 'string' && payload.next_cursor.length > 0 &&
        payload.next_cursor.length <= 4096 ? payload.next_cursor : null;
      ui.more.hidden = !nextCursor;
      ui.list.hidden = itemCount === 0;
      setNotice(itemCount
        ? `Showing ${itemCount} of your analyses. Only you can access your reports after signing in.`
        : 'No analyses yet. Upload a rowing video in the analyzer to get started.');
    } catch (error) {
      setNotice(error && error.name === 'AbortError'
        ? 'The request timed out. Refresh your history to try again.'
        : (error && error.message ? error.message : 'Your analysis history is temporarily unavailable.'), 'error');
    } finally {
      clearTimeout(timeout);
      loading = false;
      ui.more.disabled = false;
      ui.refresh.disabled = false;
    }
  }

  ui.refresh.addEventListener('click', () => loadHistory(true));
  ui.more.addEventListener('click', () => loadHistory(false));
  ui.closeVideo.addEventListener('click', clearVideo);
  ui.refreshVideo.addEventListener('click', () => {
    if (activeVideoJob) watchAnnotatedVideo(activeVideoJob);
  });
  loadHistory(true);
})();
