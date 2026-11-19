// Browser-only report-media presentation helpers. Never execute report HTML.
// Structured artifacts from our authenticated API are preferred. Legacy HTML
// contributes only explicitly allowlisted, bounded, embedded raster images.
const TRACK_PATTERN = /^R(?:[1-9]|1[0-6])$/;
const MAX_TRACKS = 16;
const MAX_FRAMES_PER_TRACK = 24;
const MAX_TOTAL_FRAMES = 192;
const MAX_EMBEDDED_BYTES = 300_000;
const MAX_REPORT_HTML_LENGTH = 24 * 1024 * 1024;

function trackOrder(track) {
  return Number(track.slice(1));
}

function s3Bucket(hostname) {
  const match = /^([a-z0-9][a-z0-9.-]{1,62})\.s3(?:\.us-east-1)?\.amazonaws\.com$/i.exec(hostname);
  return match ? match[1].toLowerCase() : '';
}

export function safePrivateMediaUrl(candidate, reportDownloadUrl, kind = '') {
  if (typeof candidate !== 'string' || typeof reportDownloadUrl !== 'string') return '';
  try {
    const media = new URL(candidate);
    const report = new URL(reportDownloadUrl);
    if (media.protocol !== 'https:' || report.protocol !== 'https:' ||
        media.username || media.password || media.hash ||
        !media.searchParams.has('X-Amz-Signature')) return '';
    if (kind === 'image' && !/\.(?:jpe?g|png|webp)$/i.test(media.pathname)) return '';
    if (kind === 'video' && !/\.(?:mp4|webm)$/i.test(media.pathname)) return '';
    const mediaBucket = s3Bucket(media.hostname);
    const reportBucket = s3Bucket(report.hostname);
    return mediaBucket && mediaBucket === reportBucket ? media.href : '';
  } catch (_) {
    return '';
  }
}

function textLabel(value, fallback) {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 180) : fallback;
}

function timeValue(value) {
  if (value === null || value === undefined || value === '') return null;
  const result = Number(value);
  return Number.isFinite(result) && result >= 0 && result <= 86400 ? result : null;
}

export function normalizeMediaArtifacts(artifacts, reportDownloadUrl) {
  const rowers = [];
  const source = artifacts && typeof artifacts.rowers === 'object' && !Array.isArray(artifacts.rowers)
    ? artifacts.rowers : {};
  let totalFrames = 0;
  const names = Object.keys(source).filter(name => TRACK_PATTERN.test(name))
    .sort((a, b) => trackOrder(a) - trackOrder(b)).slice(0, MAX_TRACKS);
  for (const track of names) {
    const group = source[track];
    if (!group || typeof group !== 'object') continue;
    const frames = [];
    const pushFrame = (entry, fallback) => {
      if (frames.length >= MAX_FRAMES_PER_TRACK || totalFrames >= MAX_TOTAL_FRAMES ||
          !entry || typeof entry !== 'object') return;
      const url = safePrivateMediaUrl(entry.url, reportDownloadUrl, 'image');
      if (!url) return;
      frames.push({ url, label: textLabel(entry.label, fallback), timeSeconds: timeValue(entry.time_seconds) });
      totalFrames += 1;
    };
    if (Array.isArray(group.snapshots)) {
      for (const snapshot of group.snapshots) pushFrame(snapshot, track + ' · technique snapshot');
    }
    if (Array.isArray(group.mistake_sequences)) {
      for (const sequence of group.mistake_sequences.slice(0, MAX_FRAMES_PER_TRACK)) {
        if (!sequence || !Array.isArray(sequence.frames)) continue;
        const stroke = Number.isSafeInteger(sequence.stroke) && sequence.stroke > 0
          ? ' · stroke ' + sequence.stroke : '';
        const issue = textLabel(sequence.code, 'Technique sequence').replace(/[_-]+/g, ' ');
        for (const frame of sequence.frames) {
          pushFrame(frame, track + ' · ' + issue + stroke);
        }
      }
    }
    rowers.push({ track, frames });
  }
  return { videoUrl: safePrivateMediaUrl(artifacts?.video_url, reportDownloadUrl, 'video'), rowers };
}

function decodeEntities(source) {
  return source.replace(/&(?:amp|quot|apos|lt|gt|#(\d+)|#x([\da-f]+));/gi, (match, decimal, hex) => {
    if (decimal || hex) {
      const point = Number.parseInt(decimal || hex, hex ? 16 : 10);
      return Number.isInteger(point) && point >= 32 && point <= 0x10ffff
        ? String.fromCodePoint(point) : '';
    }
    return { '&amp;': '&', '&quot;': '"', '&apos;': "'", '&lt;': '<', '&gt;': '>' }[match.toLowerCase()] || '';
  });
}

export function extractLegacyReportFrames(reportHtml, rowerMetrics = []) {
  if (typeof reportHtml !== 'string' || reportHtml.length > MAX_REPORT_HTML_LENGTH) return [];
  const found = new Map();
  // Capture cards and image tags as text; never place the original HTML in the
  // page. The strict data URL allows only PNG, JPEG or WebP raster images.
  const sections = /<section\b([^>]*)>([\s\S]*?)<\/section\s*>/gi;
  let match;
  let total = 0;
  while ((match = sections.exec(reportHtml)) && found.size < MAX_TRACKS && total < MAX_TOTAL_FRAMES) {
    if (!/\bclass\s*=\s*(['"])[^'"]*\bcard\b[^'"]*\1/i.test(match[1])) continue;
    const heading = /<header\b[^>]*>\s*<h2\b[^>]*>\s*(R\d{1,2})\s*<\/h2>/i.exec(match[2]);
    if (!heading || !TRACK_PATTERN.test(heading[1])) continue;
    const track = heading[1];
    if (found.has(track)) continue;
    const shotsAt = match[2].search(/<div\b[^>]*\bclass\s*=\s*(['"])shots\1/i);
    if (shotsAt < 0) continue;
    const afterShots = match[2].slice(shotsAt);
    const beforeDetail = afterShots.search(/<details\b/i);
    const snapshotHtml = beforeDetail >= 0 ? afterShots.slice(0, beforeDetail) : afterShots;
    const frames = [];
    const imageTags = /<img\b[^>]*>/gi;
    let image;
    while ((image = imageTags.exec(snapshotHtml)) &&
           frames.length < MAX_FRAMES_PER_TRACK && total < MAX_TOTAL_FRAMES) {
      const src = /\bsrc\s*=\s*(['"])(data:image\/(?:png|jpeg|webp);base64,[a-z0-9+/=]+)\1/i.exec(image[0]);
      if (!src || src[2].length > MAX_EMBEDDED_BYTES || src[2].length < 100) continue;
      const alt = /\balt\s*=\s*(['"])([^'"]{0,200})\1/i.exec(image[0]);
      const label = alt ? decodeEntities(alt[2]) : track + ' · technique snapshot ' + (frames.length + 1);
      frames.push({ url: src[2], label: textLabel(label, track + ' · technique snapshot'), timeSeconds: null });
      total += 1;
    }
    found.set(track, frames);
  }
  if (Array.isArray(rowerMetrics)) {
    for (const rower of rowerMetrics) {
      const track = rower && rower.seat;
      if (TRACK_PATTERN.test(track) && !found.has(track) && found.size < MAX_TRACKS) found.set(track, []);
    }
  }
  return Array.from(found.entries())
    .sort(([a], [b]) => trackOrder(a) - trackOrder(b))
    .map(([track, frames]) => ({ track, frames }));
}
