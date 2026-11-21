import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const variables = readFileSync(new URL('../../infra/aws/variables.tf', import.meta.url), 'utf8');
const terraform = readFileSync(new URL('../../infra/aws/gpu_recovery.tf', import.meta.url), 'utf8');
const gpu = readFileSync(new URL('../../strokesense/aws_app/gpu_recovery.py', import.meta.url), 'utf8');
const dispatcher = readFileSync(new URL('../../strokesense/aws_app/gpu_dispatcher.py', import.meta.url), 'utf8');

test('GPU recovery Terraform defaults to zero resources and disabled scheduling', () => {
  assert.match(variables, /variable "enable_paid_gpu_queue_scaffold"\s*\{[\s\S]*?default\s*=\s*false/);
  const guards = [...terraform.matchAll(/count\s*=\s*var\.enable_paid_gpu_queue_scaffold\s*\?\s*1\s*:\s*0/g)];
  assert.equal(guards.length, 9, 'all GPU recovery resources and data sources must be opt-in');
  assert.match(terraform, /resource "aws_cloudwatch_event_rule" "gpu_reconcile"[\s\S]*?state\s*=\s*"DISABLED"/);
  assert.match(terraform, /GPU_RECONCILE_ENABLED\s*=\s*"false"/);
  assert.match(terraform, /PAID_BILLING_ENABLED\s*=\s*"false"/);
  assert.match(terraform, /PAID_GPU_ENABLED\s*=\s*"false"/);
  assert.match(terraform, /GPU_DISPATCH_READY\s*=\s*"false"/);
  assert.doesNotMatch(terraform, /"ecs:RunTask"|"ecs:StopTask"|"iam:PassRole"/);
  assert.match(terraform, /"sqs:SendMessage"/);
  assert.match(terraform, /"ecs:DescribeTasks"/);
});

test('DynamoDB GSI recovery always strongly rechecks jobs and refuses old launches', () => {
  assert.match(gpu, /IndexName="status-expires_at-index"/);
  assert.match(gpu, /ConsistentRead=True/);
  assert.match(gpu, /MAX_OUTBOX_AGE_SECONDS\s*=\s*24 \* 3600/);
  assert.match(gpu, /gpu_dispatching/);
  assert.match(gpu, /manual_review/);
  assert.match(dispatcher, /gpu_dispatch_started_at/);
  assert.match(dispatcher, /23 \* 3600/);
  assert.match(dispatcher, /gpu_task_deadline_epoch/);
  assert.match(dispatcher, /gpu_queued_at/);
});
