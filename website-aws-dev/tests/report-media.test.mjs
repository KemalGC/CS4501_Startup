import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { extractLegacyReportFrames, normalizeMediaArtifacts, safePrivateMediaUrl } from '../assets/report-media-model.mjs';

const bucket = 'strokesense-private-example-123';
const reportUrl = `https://${bucket}.s3.us-east-1.amazonaws.com/reports/a/report.json?X-Amz-Signature=report`;
const signed = (path) => `https://${bucket}.s3.amazonaws.com/${path}?X-Amz-Signature=frame`;

test('S3 artifacts must be secure, signed and from the same private report bucket', () => {
  assert.equal(safePrivateMediaUrl(signed('reports/a/R2/frame.jpg'), reportUrl), signed('reports/a/R2/frame.jpg'));
  assert.equal(safePrivateMediaUrl('https://evil.test/picture.jpg?X-Amz-Signature=frame', reportUrl), '');
  assert.equal(safePrivateMediaUrl(signed('image.jpeg').replace('?X-Amz-Signature=frame', ''), reportUrl), '');
  assert.equal(safePrivateMediaUrl(signed('video.mp4').replace('https:', 'http:'), reportUrl), '');
  assert.equal(safePrivateMediaUrl(signed('video.mp4').replace(bucket, 'different-bucket'), reportUrl), '');
  assert.equal(safePrivateMediaUrl(signed('reports/a/evil.svg'), reportUrl, 'image'), '');
  assert.equal(safePrivateMediaUrl(signed('reports/a/image.png'), reportUrl, 'video'), '');
  assert.equal(safePrivateMediaUrl('data:image/svg+xml,<svg onload=alert(1)>', reportUrl), '');
});

test('structured snapshots and mistake frames are grouped by actual model track', () => {
  const artifacts = {
    video_url: signed('reports/a/annotated.mp4'),
    rowers: {
      R3: {
        snapshots: [{ label: 'Catch reference', time_seconds: 1.25, url: signed('reports/a/r3-catch.jpg') }],
        mistake_sequences: [{ code: 'early_body', stroke: 2, frames: [
          { label: 'Before', time_seconds: 3.1, url: signed('reports/a/r3-before.jpg') },
          { label: 'After', time_seconds: 3.4, url: 'https://evil.test/inject.jpg?X-Amz-Signature=oops' }
        ] }]
      },
      R1: { snapshots: [] },
      R0: { snapshots: [{ url: signed('invalid.jpg') }] }
    }
  };
  const normalized = normalizeMediaArtifacts(artifacts, reportUrl);
  assert.equal(normalized.videoUrl, signed('reports/a/annotated.mp4'));
  assert.deepEqual(normalized.rowers.map(rower => [rower.track, rower.frames.length]), [['R1', 0], ['R3', 2]]);
  assert.equal(normalized.rowers[1].frames[0].label, 'Catch reference');
  assert.equal(normalized.rowers[1].frames[1].label, 'Before');
  assert.equal(normalized.rowers[1].frames[1].timeSeconds, 3.1);
});

test('legacy report extraction uses only bounded embedded raster data, no untrusted HTML', () => {
  const image = 'data:image/png;base64,' + 'A'.repeat(260);
  const malicious = 'https://evil.test/driveby.jpg';
  const html = `<section class="card"><header><h2>R2</h2></header>
    <div class="shots"><figure><img src="${image}" alt="R2 &amp; catch"></figure>
    <figure><img src="${malicious}" onerror="alert(1)"></figure>
    <figure><img src="data:image/svg+xml;base64,${'A'.repeat(260)}"></figure></div>
    <details><summary>More detail</summary></details></section>`;
  const rowers = extractLegacyReportFrames(html, [{ seat: 'R1' }, { seat: 'R2' }]);
  assert.deepEqual(rowers.map(rower => [rower.track, rower.frames.length]), [['R1', 0], ['R2', 1]]);
  assert.equal(rowers[1].frames[0].url, image);
  assert.equal(rowers[1].frames[0].label, 'R2 & catch');
  assert.deepEqual(extractLegacyReportFrames('<section class="card">' + 'x'.repeat(25_000_000) + '</section>'), []);
});

test('the analyzer page wires consent and a securely embedded media viewer', () => {
  const page = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');
  const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
  const viewer = readFileSync(new URL('../assets/report-media.js', import.meta.url), 'utf8');
  const config = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
  const csp = config.headers[0].headers.find(header => header.key === 'Content-Security-Policy').value;
  assert.match(page, /<input id="allow-admin-review" type="checkbox"/);
  assert.doesNotMatch(page, /id="allow-admin-review"[^>]*checked/);
  assert.match(client, /allow_admin_review: ui\.adminConsent\.checked === true/);
  assert.match(client, /ui\.adminConsent\.checked = false/);
  assert.match(page, /<video id="annotated-video" controls playsinline preload="metadata"/);
  assert.match(page, /<section id="report-media"[^>]*hidden>/);
  assert.match(client, /\/artifacts'/);
  assert.match(viewer, /window\.StrokeSenseMediaViewer = \{ render: renderMedia, clear: clearMedia \}/);
  assert.match(csp, /img-src [^;]*https:\/\/\*\.s3\.us-east-1\.amazonaws\.com/);
  assert.match(page, /<iframe[^>]*\bsandbox=""/);
  assert.doesNotMatch(viewer, /innerHTML\s*=/);
});
