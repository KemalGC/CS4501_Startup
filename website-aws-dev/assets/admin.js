/* Restricted staff review UI. AWS enforces admin allowlisting and owner consent. */
(() => {
  'use strict';

  const AUTH_KEY = 'strokesense-aws-dev-auth';
  const JOB_ID = /^[a-f0-9]{32}$/;
  // This isolated AWS dev site only plays signed media from its own S3 bucket.
  const MEDIA_BUCKET = 'strokesense-aws-dev-851226124502-us-east-1';
  const config = window.STROKESENSE_AWS_CONFIG || {};
  const $ = id => document.getElementById(id);
  const ui = {
    account: $('admin-account'), signIn: $('admin-sign-in'),
    refresh: $('admin-refresh'), notice: $('admin-notice'),
    list: $('admin-list'), more: $('admin-more'),
    panel: $('admin-video-panel'), player: $('admin-video-player'),
    videoTitle: $('admin-video-title'), videoNotice: $('admin-video-notice'),
    closeVideo: $('admin-close-video'), refreshVideo: $('admin-refresh-video')
  };
  if (Object.values(ui).some(element => !element)) return;

  let apiBase = '';
  try {
    const url = new URL(config.apiBaseUrl);
    if (url.protocol === 'https:') apiBase = url.origin;
  } catch (_) { /* Don't contact an unconfigured API. */ }

  let nextCursor = null;
  let itemCount = 0;
  let loading = false;
  let viewing = false;
  let activeJob = null;
  let viewerGeneration = 0;
  const renderedIds = new Set();

  function readAuth() {
    try {
      const auth = JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null');
      return auth && typeof auth.accessToken === 'string' && auth.accessToken &&
        Number(auth.expiresAt) > Date.now() + 15_000 ? auth : null;
    } catch (_) { return null; }
  }

  function notice(message, tone = '') {
    ui.notice.textContent = message;
    ui.notice.dataset.tone = tone;
  }

  function videoNotice(message, tone = '') {
    ui.videoNotice.textContent = message;
    ui.videoNotice.dataset.tone = tone;
  }

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  }

  function dateOf(value) {
    if (value === null || value === undefined || value === '') return null;
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function displayDate(value) {
    const date = dateOf(value);
    return date ? date.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    }) : 'Not recorded';
  }

  function duration(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
    const rounded = Math.round(value);
    const minutes = Math.floor(rounded / 60);
    return minutes ? minutes + ':' + String(rounded % 60).padStart(2, '0') : rounded + ' sec';
  }

  function filename(value) {
    return typeof value === 'string' && value.trim()
      ? (value.split(/[\\/]/).pop().trim().slice(0, 150) || 'Rowing video')
      : 'Rowing video';
  }

  function detail(label, value) {
    const wrapper = node('div', 'library-field');
    wrapper.appendChild(node('dt', '', label));
    wrapper.appendChild(node('dd', '', value));
    return wrapper;
  }

  function clearVideo() {
    viewerGeneration += 1;
    activeJob = null;
    if (typeof ui.player.pause === 'function') ui.player.pause();
    ui.player.removeAttribute('src');
    if (typeof ui.player.load === 'function') ui.player.load();
    ui.panel.hidden = true;
    ui.refreshVideo.disabled = false;
  }

  function clearList() {
    nextCursor = null;
    itemCount = 0;
    renderedIds.clear();
    ui.list.replaceChildren();
    ui.list.hidden = true;
    ui.more.hidden = true;
  }

  function signedOut(message) {
    clearList();
    clearVideo();
    ui.account.textContent = 'Not signed in';
    ui.signIn.hidden = false;
    ui.refresh.hidden = true;
    notice(message || 'Sign in using an authorized staff account. Account ownership is verified by AWS.');
  }

  function forbidden() {
    clearList();
    clearVideo();
    ui.account.textContent = 'Staff authorization required';
    ui.signIn.hidden = true;
    ui.refresh.hidden = true;
    notice('This account does not have permission to review videos. Only authorized, consented recordings can be accessed.', 'error');
  }

  function jobCard(job) {
    const card = node('article', 'library-card');
    const top = node('div', 'library-card-top');
    const heading = node('div');
    heading.appendChild(node('span', 'library-card-eyebrow', 'Owner consent confirmed'));
    heading.appendChild(node('h3', '', filename(job.filename)));
    top.appendChild(heading);
    const badge = node('span', 'library-badge', 'Opted in');
    badge.dataset.tone = 'ready';
    top.appendChild(badge);
    card.appendChild(top);

    const details = node('dl', 'library-fields');
    details.appendChild(detail('Created', displayDate(job.created_at)));
    details.appendChild(detail('Status', String(job.status || 'unknown').replace(/_/g, ' ')));
    if (job.duration_seconds !== null && job.duration_seconds !== undefined) {
      const clip = duration(job.duration_seconds);
      if (clip) details.appendChild(detail('Clip duration', clip));
    }
    if (typeof job.analysis_wall_ms === 'number') {
      const elapsed = duration(job.analysis_wall_ms / 1000);
      if (elapsed) details.appendChild(detail('Analysis wall time', elapsed));
    }
    if (typeof job.cpu_time_ms === 'number') {
      const cpu = duration(job.cpu_time_ms / 1000);
      if (cpu) details.appendChild(detail('CPU time', cpu));
    }
    if (typeof job.queue_wait_ms === 'number') {
      const queued = duration(job.queue_wait_ms / 1000);
      if (queued) details.appendChild(detail('Queue wait', queued));
    }
    if (typeof job.batch_run_ms === 'number') {
      const run = duration(job.batch_run_ms / 1000);
      if (run) details.appendChild(detail('Batch run', run));
    }
    if (job.video_expires_at) details.appendChild(detail('Video retained until', displayDate(job.video_expires_at)));
    card.appendChild(details);

    const actions = node('div', 'library-card-actions');
    if (job.video_available !== false) {
      const button = node('button', 'pill pill-coral', 'Review permitted video');
      button.type = 'button';
      button.addEventListener('click', () => requestVideo(job));
      actions.appendChild(button);
    } else {
      actions.appendChild(node('span', 'library-action-note', 'Video retention ended; playback unavailable.'));
    }
    actions.appendChild(node('span', 'library-action-note',
      'Availability and owner consent are checked again before playback.'));
    card.appendChild(actions);
    return card;
  }

  function validVideoUrl(value) {
    try {
      const url = new URL(value);
      const host = url.hostname.toLowerCase();
      if (url.protocol !== 'https:' || url.username || url.password || url.hash ||
          !url.searchParams.has('X-Amz-Signature') || !url.searchParams.get('X-Amz-Signature') ||
          ![
            MEDIA_BUCKET + '.s3.us-east-1.amazonaws.com',
            MEDIA_BUCKET + '.s3.amazonaws.com'
          ].includes(host)) return null;
      return url;
    } catch (_) { return null; }
  }

  async function requestVideo(job) {
    if (viewing || !job || job.allow_admin_review !== true || !JOB_ID.test(job.job_id)) return;
    const auth = readAuth();
    if (!auth) { signedOut('Staff sign-in expired. Sign in again to request video access.'); return; }
    if (!apiBase) { videoNotice('AWS API is not configured.', 'error'); return; }
    viewing = true;
    clearVideo();
    const generation = viewerGeneration;
    activeJob = job;
    ui.panel.hidden = false;
    ui.videoTitle.textContent = 'Review ' + filename(job.filename);
    ui.refreshVideo.disabled = true;
    videoNotice('Requesting short-lived video access…');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/admin/videos/' + encodeURIComponent(job.job_id), {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (generation !== viewerGeneration) return;
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Staff sign-in expired. Sign in again to request video access.');
        return;
      }
      if (response.status === 403) {
        clearVideo();
        notice('Video access was denied. Owner consent or staff authorization may have changed; refresh the review list.', 'error');
        return;
      }
      if (response.status === 404 || response.status === 410) {
        clearVideo();
        notice('Video is unavailable or owner consent was withdrawn. Refresh the review list.', 'error');
        return;
      }
      if (!response.ok) throw Error('AWS could not issue a temporary video link.');
      const data = await response.json();
      if (generation !== viewerGeneration) return;
      const videoUrl = validVideoUrl(data && data.video_url);
      if (!data || data.job_id !== job.job_id || !videoUrl) {
        throw Error('The video service returned an invalid secure video URL.');
      }
      // No presigned URL appears in page text or logs. The native video element
      // alone receives it, and it is removed when the viewer is closed.
      ui.player.src = videoUrl.toString();
      if (typeof ui.player.load === 'function') ui.player.load();
      const source = data.video_type === 'annotated' ? 'Annotated analysis' :
        data.video_type === 'original' ? 'Original footage' : 'Consented video';
      const seconds = Number.isFinite(Number(data.expires_in))
        ? Math.min(60, Math.max(1, Math.round(Number(data.expires_in)))) : 60;
      videoNotice(`${source} · viewing link lasts up to ${seconds} seconds. If seeking stops, refresh video access.`);
    } catch (error) {
      if (generation !== viewerGeneration) return;
      clearVideo();
      notice(error && error.name === 'AbortError'
        ? 'Video access request timed out. Please try again.'
        : 'Unable to open video: ' + (error?.message || 'unknown error'), 'error');
    } finally {
      clearTimeout(timeout);
      viewing = false;
      ui.refreshVideo.disabled = false;
    }
  }

  async function loadReviews(reset = false) {
    if (loading) return;
    const auth = readAuth();
    if (!auth) { signedOut(); return; }
    ui.account.textContent = 'Signed in · staff authorization checked by AWS';
    ui.signIn.hidden = true;
    ui.refresh.hidden = false;
    if (!apiBase) { notice('AWS API is not configured.', 'error'); return; }

    if (reset) { clearList(); clearVideo(); }
    loading = true;
    ui.more.disabled = true;
    ui.refresh.disabled = true;
    notice('Loading consented reviews…');
    const url = new URL(apiBase + '/admin/jobs');
    url.searchParams.set('limit', '20');
    if (nextCursor) url.searchParams.set('cursor', nextCursor);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.toString(), {
        method: 'GET', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer ' + auth.accessToken }, signal: controller.signal
      });
      if (response.status === 401) {
        try { sessionStorage.removeItem(AUTH_KEY); } catch (_) {}
        signedOut('Staff sign-in expired. Sign in again to request video access.');
        return;
      }
      if (response.status === 403) { forbidden(); return; }
      if (response.status === 404) {
        clearList();
        notice('Staff review is not yet available in the AWS backend.', 'error');
        return;
      }
      if (!response.ok) throw Error('Could not load the consented review list.');
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.jobs)) throw Error('Unexpected response from the review service.');
      for (const job of payload.jobs) {
        if (!job || job.allow_admin_review !== true || typeof job.job_id !== 'string' ||
            !JOB_ID.test(job.job_id) || renderedIds.has(job.job_id)) continue;
        renderedIds.add(job.job_id);
        ui.list.appendChild(jobCard(job));
        itemCount += 1;
      }
      nextCursor = typeof payload.next_cursor === 'string' && payload.next_cursor.length > 0 &&
        payload.next_cursor.length <= 4096 ? payload.next_cursor : null;
      ui.more.hidden = !nextCursor;
      ui.list.hidden = itemCount === 0;
      notice(itemCount ? `Showing ${itemCount} opted-in review(s). Access is rechecked for every video.`
        : 'No videos are currently shared for staff review.');
    } catch (error) {
      notice(error && error.name === 'AbortError' ? 'Loading reviews timed out. Please refresh.'
        : 'Unable to load reviews. Please try again later.', 'error');
    } finally {
      clearTimeout(timeout);
      loading = false;
      ui.more.disabled = false;
      ui.refresh.disabled = false;
    }
  }

  ui.refresh.addEventListener('click', () => loadReviews(true));
  ui.more.addEventListener('click', () => loadReviews(false));
  ui.closeVideo.addEventListener('click', clearVideo);
  ui.refreshVideo.addEventListener('click', () => { if (activeJob) requestVideo(activeJob); });
  loadReviews(true);
})();
