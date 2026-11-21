import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const code = readFileSync(new URL('../../infra/aws/gpu-smoke.ps1', import.meta.url), 'utf8');
test('operator GPU smoke requires charge/account approval and AWS-side cutoff before launch', () => {
  assert.ok(code.includes('-ExpectedAccountId'));
  assert.ok(code.includes('ApproveCharge'));
  assert.ok(code.includes("get-caller-identity"));
  assert.ok(code.includes('put-scheduled-update-group-action'));
  assert.ok(code.includes('describe-scheduled-actions'));
  assert.ok(code.indexOf("put-scheduled-update-group-action") < code.indexOf("'--desired-capacity','1'"));
  assert.ok(code.includes("'--max-size','0','--desired-capacity','0'"));
  assert.ok(code.includes("'--max-size','1','--desired-capacity','1'"));
  assert.ok(code.includes("gpu_smoke_task_definition"));
  assert.ok(code.includes('NO customer task role'));
  assert.ok(code.includes('finally {'));
  assert.ok(!code.includes('terraform apply'));
});
