// No AWS calls or credentials: enforce review-only GPU capacity defaults.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tf = readFileSync(new URL('../../infra/aws/gpu_capacity.tf', import.meta.url), 'utf8');
const vars = readFileSync(new URL('../../infra/aws/variables.tf', import.meta.url), 'utf8');
const queue = readFileSync(new URL('../../infra/aws/gpu_queue.tf', import.meta.url), 'utf8');
const recover = readFileSync(new URL('../../infra/aws/gpu_recovery.tf', import.meta.url), 'utf8');
const dispatch = readFileSync(new URL('../../strokesense/aws_app/gpu_dispatcher.py', import.meta.url), 'utf8');

test('paid GPU resources stay off by default; smoke is a separate opt-in', () => {
  assert.match(vars, /variable "enable_gpu"\s*\{[\s\S]*?default\s*=\s*false/);
  assert.match(vars, /condition\s*=\s*!var\.enable_gpu/);
  assert.match(vars, /var\.gpu_smoke_mode/);
  assert.match(vars, /I_APPROVE_ONE_G6F_SMOKE_INSTANCE/);
  assert.match(vars, /!var\.enable_paid_gpu_queue_scaffold/);
  assert.match(vars, /!var\.enable_cpu_analysis/);
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

test('smoke host cannot auto-launch and must stay at one instance', () => {
  assert.match(tf, /managed_scaling\s*\{[\s\S]*?status\s*=\s*var\\.gpu_smoke_mode \? "DISABLED"/);
  assert.match(tf, /protect_from_scale_in\s*=\s*!var\\.gpu_smoke_mode/);
  assert.match(tf, /resource "aws_ecs_task_definition" "gpu_preflight"/);
  assert.match(tf, /name\s*=\s*"gpu-preflight"/);
  assert.match(tf, /command\s*=\s*\["python3", "-m", "aws_app.gpu_preflight"/);
  assert.match(tf, /resourceRequirements = \[\s*\{ type = "GPU", value = "0.125" \\}/);
  const ecr = readFileSync(new URL('../../infra/aws/gpu_ecr.tf', import.meta.url), 'utf8');
  assert.match(ecr, /count\s*=\s*var.enable_gpu_image_repository \? 1 : 0/);
  assert.match(ecr, /image_tag_mutability\s*=\s*"IMMUTABLE"/);
});
