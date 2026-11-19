/* Community browsing uses no Cognito token. Only the API can publish videos. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ui = {
    mine: $('library-private-section'), public: $('library-community-section'),
    mineTab: $('library-tab-private'), publicTab: $('library-tab-community'),
    refresh: $('community-refresh'), list: $('community-list'),
    notice: $('community-notice'), more: $('community-more'),
    panel: $('community-video-panel'), player: $('community-video-player'),
    link: $('community-video-link'), close: $('community-close-video'),
    refreshVideo: $('community-refresh-video'), videoNotice: $('community-video-notice'),
    videoTitle: $('community-video-title')
  };
  if (Object.values(ui).some(element => !element)) return;
  const jobIdPattern = /^[a-f0-9]{32}$/;
  const mediaBucket = 'strokesense-aws-dev-851226124502-us-east-1';
  const config = window.STROKESENSE_AWS_CONFIG || {};
  let apiBase = '';
  try {
    const parsed = new URL(config.apiBaseUrl);
    if (parsed.protocol === 'https:') apiBase = parsed.origin;
  } catch (_) {}
  let cursor = null;
  let count = 0;
  let loading = false;
  let loaded = false;
  let selectedId = null;
  let playerGeneration = 0;
  let playerTimer = null;
  const seen = new Set();

  function notify(message, tone = '') {
    ui.notice.textContent = message;
    ui.notice.dataset.tone = tone;
  }
  function dateLabel(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleDateString();
  }
  function safeVideoUrl(value) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.hash ||
          !parsed.searchParams.has('X-Amz-Signature') ||
          ![mediaBucket + '.s3.us-east-1.amazonaws.com', mediaBucket + '.s3.amazonaws.com']
            .includes(parsed.hostname.toLowerCase())) return null;
      return parsed.toString();
    } catch (_) { return null; }
  }
  function clearPlayer() {
    playerGeneration++;
    if (playerTimer !== null) clearTimeout(playerTimer);
    playerTimer = null;
    if (typeof ui.player.pause === 'function') ui.player.pause();
    ui.player.removeAttribute('src');
    if (typeof ui.player.load === 'function') ui.player.load();
    ui.link.removeAttribute('href');
    ui.link.hidden = true;
    ui.panel.hidden = true;
  }
  async function watchVideo(id) {
    if (!jobIdPattern.test(id)) return;
    selectedId = id;
    clearPlayer();
    const generation = playerGeneration;
    ui.panel.hidden = false;
    ui.videoTitle.textContent = 'Community rowing session';
    ui.videoNotice.textContent = 'Requesting a short-lived link to this shared annotated clip…';
    if (!apiBase) { ui.videoNotice.textContent = 'Community video service is not configured.'; return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/community/videos/' + encodeURIComponent(id), {
        method: 'GET', credentials: 'omit', cache: 'no-store', signal: controller.signal
      });
      if (generation !== playerGeneration) return;
      if (response.status === 404 || response.status === 410) {
        ui.videoNotice.textContent = 'This video has been unpublished or has expired.';
        return;
      }
      if (!response.ok) throw Error('Unable to load this community video.');
      const payload = await response.json();
      if (generation !== playerGeneration) return;
      if (!payload || payload.job_id !== id || payload.video_type !== 'annotated') throw Error('Invalid video response.');
      const url = safeVideoUrl(payload.video_url);
      if (!url) throw Error('Invalid secure playback link.');
      ui.player.src = url;
      if (typeof ui.player.load === 'function') ui.player.load();
      ui.link.href = url;
      ui.link.hidden = false;
      const seconds = Number.isFinite(Number(payload.expires_in)) ? Math.min(60, Math.max(1, Number(payload.expires_in))) : 60;
      ui.videoNotice.textContent = 'Shared by its owner. Temporary access expires in up to ' + seconds + ' seconds. Refresh the link if playback stops.';
      playerTimer = setTimeout(() => {
        if (generation !== playerGeneration) return;
        ui.link.removeAttribute('href');
        ui.link.hidden = true;
        ui.videoNotice.textContent = 'The playback link expired. Request another if the owner still shares this video.';
      }, seconds * 1000);
    } catch (error) {
      if (generation === playerGeneration) ui.videoNotice.textContent = error?.name === 'AbortError'
        ? 'The video request timed out. Try again.'
        : 'Could not open the shared video. Try again.';
    } finally { clearTimeout(timeout); }
  }
  function videoCard(video) {
    const article = document.createElement('article');
    article.className = 'community-card';
    const eyebrow = document.createElement('span');
    eyebrow.className = 'library-card-eyebrow';
    eyebrow.textContent = 'Publicly shared annotated video';
    article.appendChild(eyebrow);
    const heading = document.createElement('h3');
    heading.textContent = 'Rowing session';
    article.appendChild(heading);
    const info = document.createElement('p');
    const duration = typeof video.duration_seconds === 'number' && video.duration_seconds > 0
      ? ' · ' + Math.round(video.duration_seconds) + ' sec clip' : '';
    info.textContent = 'Shared ' + dateLabel(video.published_at || video.created_at) + duration;
    article.appendChild(info);
    const action = document.createElement('button');
    action.className = 'library-watch-video';
    action.type = 'button';
    action.textContent = 'Watch annotated video';
    action.addEventListener('click', () => watchVideo(video.job_id));
    article.appendChild(action);
    return article;
  }
  async function loadVideos(reset = false) {
    if (loading) return;
    if (reset) {
      cursor = null;
      count = 0;
      seen.clear();
      ui.list.replaceChildren();
      ui.list.hidden = true;
      clearPlayer();
    }
    loaded = true;
    if (!apiBase) { notify('The community API is not configured.', 'error'); return; }
    loading = true;
    ui.refresh.disabled = true;
    ui.more.disabled = true;
    notify('Loading publicly shared videos…');
    const url = new URL(apiBase + '/community/videos');
    url.searchParams.set('limit', '12');
    if (cursor) url.searchParams.set('cursor', cursor);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.toString(), {
        method: 'GET', credentials: 'omit', cache: 'no-store', signal: controller.signal
      });
      if (!response.ok) throw Error(response.status === 404
        ? 'Community Videos is being set up. Private analyses are unaffected.'
        : 'Could not load Community Videos.');
      const result = await response.json();
      if (!result || !Array.isArray(result.videos)) throw Error('Community response was invalid.');
      for (const video of result.videos) {
        if (!video || !jobIdPattern.test(video.job_id) || seen.has(video.job_id)) continue;
        seen.add(video.job_id);
        ui.list.appendChild(videoCard(video));
        count++;
      }
      cursor = typeof result.next_cursor === 'string' && result.next_cursor.length <= 2048
        ? result.next_cursor : null;
      ui.more.hidden = !cursor;
      ui.list.hidden = count === 0;
      notify(count ? 'Showing ' + count + ' publicly shared annotated videos.' :
        'No public videos yet. Users can share completed annotated videos from My Videos.');
    } catch (error) {
      notify(error?.name === 'AbortError' ? 'Request timed out. Try refreshing.' :
        (error?.message || 'Community Videos is temporarily unavailable.'), 'error');
    } finally {
      clearTimeout(timeout);
      loading = false;
      ui.refresh.disabled = false;
      ui.more.disabled = false;
    }
  }
  function activate(tab) {
    const publicTab = tab === 'community';
    ui.mine.hidden = publicTab;
    ui.public.hidden = !publicTab;
    ui.mineTab.classList.toggle('is-active', !publicTab);
    ui.publicTab.classList.toggle('is-active', publicTab);
    ui.mineTab.setAttribute('aria-selected', String(!publicTab));
    ui.publicTab.setAttribute('aria-selected', String(publicTab));
    if (publicTab && !loaded) void loadVideos(true);
    if (!publicTab) clearPlayer();
    if (window.history?.replaceState) {
      window.history.replaceState(null, '', publicTab ? '#community' : '#mine');
    }
  }
  ui.mineTab.addEventListener('click', () => activate('mine'));
  ui.publicTab.addEventListener('click', () => activate('community'));
  ui.refresh.addEventListener('click', () => loadVideos(true));
  ui.more.addEventListener('click', () => loadVideos(false));
  ui.close.addEventListener('click', () => { selectedId = null; clearPlayer(); });
  ui.refreshVideo.addEventListener('click', () => { if (selectedId) void watchVideo(selectedId); });
  activate(window.location?.hash === '#community' ? 'community' : 'mine');
})();
