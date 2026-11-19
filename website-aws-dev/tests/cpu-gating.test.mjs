import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const build = readFileSync(new URL('../build.mjs', import.meta.url), 'utf8');
const client = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');

test('public CPU analysis stays unavailable until the explicit frontend switch is enabled', () => {
  assert.match(build, /cpuAnalysisEnabled: process\.env\.STROKESENSE_ENABLE_CPU_ANALYSIS === 'true'/);
  assert.match(client, /const cpuAnalysisEnabled = config\.cpuAnalysisEnabled === true/);
  assert.match(client, /selectedTier === 'free' \? cpuAnalysisEnabled : deepAnalysisEnabled/);
  assert.match(client, /if \(tier\(\) === 'free' && !cpuAnalysisEnabled\) return/);
});

test('private job ID survives success and refresh, but is cleared on sign out or failure', () => {
  assert.match(client, /const ACTIVE_JOB_KEY = 'strokesense-aws-dev-active-job'/);
  assert.match(client, /sessionStorage\.setItem\(ACTIVE_JOB_KEY, jobId\)/);
  assert.match(client, /forgetActiveJob\(jobId\)/);
  assert.match(client, /forgetActiveJob\(\);\s*clearReport\(\)/);
  assert.match(client, /finishSignIn\(\)\.then\(\(\) => \{/);
  assert.match(client, /return resumeAnalysis\(\)/);
  assert.match(client, /waitForAnalysis\(jobId, abortController\.signal, \{ autoDownload: false \}\)/);
  assert.match(client, /90 \* 60 \* 1000/);
});
