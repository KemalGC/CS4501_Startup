import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const page = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');
const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const recent = readFileSync(new URL('../assets/recent-analyses.js', import.meta.url), 'utf8');
const CSS = readFileSync(new URL('../assets/aws-dev.css', import.meta.url), 'utf8');
const frames = readFileSync(new URL('../assets/report-frame.js', import.meta.url), 'utf8');
const video = readFileSync(new URL('../assets/report-media.js', import.meta.url), 'utf8');

test('both embedded report views expand into the page without nested scrolling', () => {
  assert.match(page, /src="\/assets\/report-frame\.js"/);
  assert.match(page, /sandbox="allow-same-origin" scrolling="no"/);
  assert.match(client, /StrokeSenseAutoReportFrame\?\.attach\(ui\.reportFrame\)/);
  assert.match(recent, /StrokeSenseAutoReportFrame\?\.attach\(frame\)/);
  assert.match(recent, /setAttribute\('sandbox', 'allow-same-origin'\)/);
  assert.match(CSS, /\.aws-history-report-frame \{[^}]*max-height: none/);
  assert.match(CSS, /\.aws-report-preview iframe \{[^}]*max-height: none/);
  assert.doesNotMatch(page, /sandbox="[^"]*allow-scripts/);
  assert.doesNotMatch(recent, /setAttribute\('sandbox', 'allow-scripts'\)/);
});

test('report frame measures content and responds to expanding report details', () => {
  const handlers = {};
  const document = {
    documentElement: { scrollHeight: 1150, offsetHeight: 1100, style: {} },
    body: { scrollHeight: 1200, offsetHeight: 1180, style: {} },
    images: [],
    addEventListener(type, callback) { handlers['doc:' + type] = callback; }
  };
  const frame = {
    attributes: {}, style: {}, contentDocument: document,
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { handlers[name] = callback; }
  };
  const win = {};
  runInNewContext(frames, {
    window: win, WeakSet, ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
    requestAnimationFrame: callback => callback(), Number, Math
  });
  win.StrokeSenseAutoReportFrame.attach(frame);
  assert.equal(frame.attributes.sandbox, 'allow-same-origin');
  assert.equal(frame.attributes.scrolling, 'no');
  handlers.load();
  assert.equal(frame.style.height, '1208px');
  document.body.scrollHeight = 2400;
  handlers['doc:toggle']();
  assert.equal(frame.style.height, '2408px');
});

test('video player provides explicit refresh and a signed S3 download fallback', () => {
  assert.match(page, /id="annotated-video-refresh"/);
  assert.match(page, /id="annotated-video-link"/);
  assert.match(video, /refreshAnnotatedVideo/);
  assert.match(video, /addEventListener\('error'/);
  assert.match(video, /X-Amz-Signature/);
  assert.match(video, /setVideoLink\(payload\.video_url, payload\.expires_in\)/);
  assert.match(video, /No annotated video was saved/);
  assert.doesNotMatch(video, /innerHTML\s*=/);
});
