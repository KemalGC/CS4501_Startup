import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const configuration = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
const policy = configuration.headers.find(item => item.source === '/(.*)')
  .headers.find(item => item.key === 'Content-Security-Policy').value;
const dashboard = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');
const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');

test('staging CSP permits the sandboxed report frame and inline report styles', () => {
  assert.match(policy, /(?:^|;\s*)frame-src 'self'(?:;|$)/);
  assert.match(policy, /(?:^|;\s*)style-src [^;]*'unsafe-inline'/);
  assert.match(policy, /(?:^|;\s*)script-src 'self'(?:;|$)/);
  assert.match(policy, /(?:^|;\s*)frame-ancestors 'none'(?:;|$)/);
  assert.match(dashboard, /<iframe[^>]*\bsandbox="allow-same-origin"/);
  assert.doesNotMatch(dashboard, /sandbox="[^"]*allow-scripts/);
});

test('report preview requires matching schema/job, keeps its frame sandboxed', () => {
  assert.match(client, /document\.schema_version !== 'strokesense-free-report-v1'/);
  assert.match(client, /document\.job_id !== jobId/);
  assert.match(client, /ui\.reportFrame\.srcdoc = document\.report_html/);
  assert.match(client, /new Blob\(\[document\.report_html\]/);
  assert.match(client, /ui\.download\.click\(\)/);
  assert.doesNotMatch(dashboard, /sandbox="[^"]*allow-scripts/);
});
