// No AWS calls or credentials: enforce review-only GPU capacity defaults.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tf = readFileSync(new URL('../../infra/aws/gpu_capacity.tf', import.meta.url), 'utf8');
const vars = readFileSync(new URL('../../infra/aws/variables.tf', import.meta.url), 'utf8');
const queue = readFileSync(new URL('../../infra/aws/gpu_queue.tf', import.meta.url), 'utf8');
const recover = readFileSync(new URL('../../infra/aws/gpu_recovery.tf', import.meta.url), 'utf8');
const dispatch = readFileSync(new URL('../../strokesense/aws_app/gpu_dispatcher.py', import.meta.url), 'utf8');

test('paid GPU resources stay gated and permanently blocked', () => {
  assert.match(vars, /variable "enable_gpu"\s*\{[\s\S]*?default\s*=\s*false[\s\S]*?condition\s*=\s*var\.enable_gpu == false/);
  for (const type of ['aws_ecs_cluster', 'aws_launch_template', 'aws_autoscaling_group', 'aws_ecs_capacity_provider', 'aws_ecs_task_definition', 'aws_vpc_endpoint']) {
    const block = tf.split('resource "' + type + '" "')[1];
    assert.ok(block, 'missing ' + type);
    assert.match(block.slice(0, 180), /count\s*=\s*var\.enable_gpu \? 1 : 0/);
  }
  assert.match(tf, /min_size\s*=\s*0/);
  assert.match(tf, /desired_capacity\s*=\s*0/);
  assert.match(tf, /max_size\s*=\s*1/);
  assert.match(tf, /instance_type\s*=\s*"g6f\.xlarge"/);
  assert.match(tf, /requires_compatibilities\s*=\s*\["EC2"\]/);
  assert.match(tf, /value\s*=\s*"0\.125"/);
  assert.match(tf, /gpu_worker_image_uri/);
  assert.doesNotMatch(tf, /resource "aws_nat_gateway"/);
});

test('queue, dispatch and automatic retries cannot start paid GPU', () => {
  assert.match(queue, /GPU_DISPATCH_ENABLED\s*=\s*"false"/);
  assert.match(queue, /enabled\s*=\s*false/);
  assert.match(recover, /GPU_RECONCILE_ENABLED\s*=\s*"false"/);
  assert.match(recover, /state\s*=\s*"DISABLED"/);
  assert.match(dispatch, /"assignPublicIp": "DISABLED"/);
  assert.doesNotMatch(dispatch, /active_job_expires_at < :now/);
});
