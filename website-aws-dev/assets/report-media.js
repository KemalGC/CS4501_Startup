import { extractLegacyReportFrames, normalizeMediaArtifacts } from './report-media-model.mjs';

// This viewer uses only browser DOM creation and textContent. The source report
// stays inside its separately sandboxed iframe, and none of the original HTML
// is interpolated into the site DOM.
const section = document.getElementById('report-media');
const tabs = document.getElementById('rower-media-tabs');
const strip = document.getElementById('rower-media-scroll');
const rowerHeading = document.getElementById('rower-media-current');
const rowerHint = document.getElementById('rower-media-source');
const video = document.getElementById('annotated-video');
const videoNote = document.getElementById('annotated-video-note');

function clearMedia() {
  if (!section) return;
  section.hidden = true;
  if (tabs) tabs.replaceChildren();
  if (strip) {
    for (const img of strip.querySelectorAll('img')) img.removeAttribute('src');
    strip.replaceChildren();
  }
  if (rowerHeading) rowerHeading.textContent = '';
  if (rowerHint) rowerHint.textContent = '';
  if (video) {
    video.pause();
    video.removeAttribute('src');
    video.hidden = true;
    video.load(); // Release any earlier private video request.
  }
  if (videoNote) videoNote.textContent = '';
}

function renderFrames(rower) {
  strip.replaceChildren();
  rowerHeading.textContent = rower.track + ' · model track';
  if (!rower.frames.length) {
    const empty = document.createElement('p');
    empty.className = 'aws-media-empty';
    empty.textContent = 'No usable still frames were provided for this model track. The full report may contain other measurements.';
    strip.append(empty);
    return;
  }

  for (const frame of rower.frames) {
    const figure = document.createElement('figure');
    figure.className = 'aws-rower-frame';
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.alt = frame.label;
    img.src = frame.url;
    const caption = document.createElement('figcaption');
    caption.textContent = frame.label + (frame.timeSeconds !== null
      ? ' · ' + frame.timeSeconds.toFixed(2) + ' s' : '');
    figure.append(img, caption);
    strip.append(figure);
  }
  strip.scrollLeft = 0;
}

function showRowers(rowers) {
  tabs.replaceChildren();
  const initial = rowers.findIndex(rower => rower.frames.length > 0);
  let selected = initial >= 0 ? initial : 0;
  const buttons = [];
  const choose = (index) => {
    selected = index;
    for (let i = 0; i < buttons.length; i++) {
      const active = i === selected;
      buttons[i].setAttribute('aria-pressed', String(active));
      buttons[i].classList.toggle('is-selected', active);
    }
    renderFrames(rowers[selected]);
  };
  rowers.forEach((rower, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'aws-rower-tab';
    button.textContent = rower.track;
    button.title = rower.frames.length
      ? rower.frames.length + ' still frames' : 'No still frames available';
    button.setAttribute('aria-label', rower.track + ', ' + rower.frames.length + ' still frames');
    button.addEventListener('click', () => choose(index));
    tabs.append(button);
    buttons.push(button);
  });
  if (rowers.length) choose(selected);
  else {
    rowerHeading.textContent = 'No rower frames available';
    const empty = document.createElement('p');
    empty.className = 'aws-media-empty';
    empty.textContent = 'This report does not contain separate photos yet. You can still read and download the complete report below.';
    strip.append(empty);
  }
}

function renderMedia(reportDocument, artifacts, reportDownloadUrl) {
  if (!section || !tabs || !strip || !rowerHeading || !rowerHint || !video || !videoNote) return;
  clearMedia();
  const structured = normalizeMediaArtifacts(artifacts, reportDownloadUrl);
  const containsStructuredFrames = structured.rowers.some(rower => rower.frames.length);
  const rowers = containsStructuredFrames ? structured.rowers :
    extractLegacyReportFrames(reportDocument?.report_html, reportDocument?.metrics?.rowers);
  const present = new Set(rowers.map(rower => rower.track));
  for (const metric of Array.isArray(reportDocument?.metrics?.rowers) ? reportDocument.metrics.rowers : []) {
    const track = metric?.seat;
    if (typeof track === 'string' && /^R(?:[1-9]|1[0-6])$/.test(track) &&
        !present.has(track) && rowers.length < 16) {
      rowers.push({ track, frames: [] });
      present.add(track);
    }
  }
  rowers.sort((a, b) => Number(a.track.slice(1)) - Number(b.track.slice(1)));
  rowerHint.textContent = !rowers.some(rower => rower.frames.length)
    ? 'Separate frame images are not available for this report yet. The complete report remains below.'
    : containsStructuredFrames
      ? 'Browse private images generated for your report. Each tab is a model track, not a verified boat seat.'
      : 'Browse still frames embedded in this report. Track labels are model IDs, not verified seat numbers.';
  showRowers(rowers);

  if (structured.videoUrl) {
    video.src = structured.videoUrl;
    video.hidden = false;
    videoNote.textContent = 'Private annotated video is available for this report. The secure playback link is temporary.';
  } else {
    videoNote.textContent = 'Annotated video is not available for this report yet. You can still explore the still frames above.';
  }
  section.hidden = false;
}

// The analysis client loads the report only after checking owner-scoped API
// state and validating report schema and matching job ID.
window.StrokeSenseMediaViewer = { render: renderMedia, clear: clearMedia };
