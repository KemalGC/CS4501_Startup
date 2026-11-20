import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const vars = readFileSync(new URL('../../infra/aws/variables.tf', import.meta.url), 'utf8');
const queue = readFileSync(new URL('../../infra/aws/gpu_queue.tf', import.meta.url), 'utf8');
const api = readFileSync(new URL('../../infra/aws/api.tf', import.meta.url), 'utf8');

test('GPU SQS queue scaffold is opt-in and has no GPU compute capacity', () => {
  assert.match(vars, /variable "enable_paid_gpu_queue_scaffold"\s*\{[\s\S]*?default\s*=\s*false\b/);
  assert.match(queue, /resource "aws_sqs_queue" "gpu_jobs"/);
  assert.match(queue, /resource "aws_sqs_queue" "gpu_dead_letter"/);
  const guarded = [...queue.matchAll(/count\s*=\s*var\.enable_paid_gpu_queue_scaffold\s*\?\s*1\s*:\s*0/g)];
  assert.equal(guarded.length, 10, 'every new queue/role/Lambda/mapping resource must be opted into');
  assert.match(queue, /resource "aws_lambda_event_source_mapping" "gpu_dispatcher"\s*\{[\s\S]*?enabled\s*=\s*false/);
  assert.match(queue, /GPU_DISPATCH_ENABLED\s*=\s*"false"/);
  assert.match(queue, /PAID_GPU_ENABLED\s*=\s*"false"/);
  assert.match(queue, /PAID_BILLING_ENABLED\s*=\s*"false"/);
  assert.doesNotMatch(queue, /"ecs:RunTask"/);
  assert.doesNotMatch(queue, /"iam:PassRole"/);
  assert.match(api, /PAID_BILLING_ENABLED\s*=\s*"false"/);
  assert.match(api, /PAID_GPU_ENABLED\s*=\s*"false"/);
});

test('queue is FIFO, encrypted, scoped and recoverable through a DLQ', () => {
  assert.match(queue, /name\s*=\s*"\$\{local.prefix\}-paid-gpu-jobs\.fifo"/);
  assert.match(queue, /fifo_queue\s*=\s*true/);
  assert.match(queue, /sqs_managed_sse_enabled\s*=\s*true/);
  assert.match(queue, /redrive_policy\s*=\s*jsonencode\(/);
  assert.match(queue, /deadLetterTargetArn\s*=\s*aws_sqs_queue\.gpu_dead_letter\[0\]\.arn/);
  assert.match(queue, /function_response_types\s*=\s*\["ReportBatchItemFailures"\]/);
  assert.match(queue, /batch_size\s*=\s*1/);
});
