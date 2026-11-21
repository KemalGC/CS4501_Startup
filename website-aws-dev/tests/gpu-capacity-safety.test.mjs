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
  const gpuGuard = vars.split('variable "enable_gpu" {')[1].split('\nvariable ')[0];
  assert.match(gpuGuard, /!var\.enable_paid_gpu_queue_scaffold/);
  assert.match(gpuGuard, /!var\.enable_cpu_smoke_queue/);
  // The isolated smoke stack must coexist with the live CPU analyzer; forcing
  // enable_cpu_analysis=false would disable production CPU on apply.
  assert.doesNotMatch(gpuGuard.split('error_message')[0], /!var\.enable_cpu_analysis/);
  const preflight = tf.split('resource "aws_ecs_task_definition" "gpu_preflight"')[1];
  assert.doesNotMatch(preflight, /task_role_arn/, 'preflight must not carry a customer-data task role');
  for (const type of ['aws_ecs_cluster', 'aws_launch_template', 'aws_autoscaling_group', 'aws_ecs_capacity_provider', 'aws_ecs_task_definition']) {
    const block = tf.split('resource "' + type + '" "')[1];
    assert.ok(block, 'missing ' + type);
    assert.match(block.slice(0, 180), /count\s*=\s*var\.enable_gpu \? 1 : 0/);
  }
  // The smoke preflight must not touch shared routing (the VPC main route
  // table also serves the live CPU analyzer); only real-data GPU gets S3.
  const endpoint = tf.split('resource "aws_vpc_endpoint" "gpu_s3"')[1];
  assert.match(endpoint.slice(0, 120), /count\s*=\s*var\.enable_gpu && !var\.gpu_smoke_mode \? 1 : 0/);
  assert.match(tf, /var\.gpu_smoke_mode \|\| length\(var\.gpu_s3_route_table_ids\) >= 1/);
  assert.match(tf, /min_size\s*=\s*0/);
  assert.match(tf, /desired_capacity\s*=\s*0/);
  // Idle smoke capacity is max 0; the operator script raises it to 1 only.
  assert.match(tf, /max_size\s*=\s*var\.gpu_smoke_mode \? 0 : 1/);
  assert.match(tf, /suspended_processes\s*=\s*var\.gpu_smoke_mode \? \["AZRebalance", "ReplaceUnhealthy"\]/);
  assert.match(tf, /managed_draining\s*=\s*var\.gpu_smoke_mode \? "DISABLED" : "ENABLED"/);
  assert.match(tf, /ECS_AWSVPC_BLOCK_IMDS=true/);
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

test('smoke host does not auto-launch and cannot exceed one instance', () => {
  assert.ok(tf.includes('status                    = var.gpu_smoke_mode ? "DISABLED" : "ENABLED"'));
  assert.ok(tf.includes('protect_from_scale_in = !var.gpu_smoke_mode'));
  assert.match(tf, /resource "aws_ecs_task_definition" "gpu_preflight"/);
  assert.match(tf, /name\s*=\s*"gpu-preflight"/);
  assert.ok(tf.includes('command   = ["python3", "-m", "aws_app.gpu_preflight"'));
  assert.match(tf, /value\s*=\s*"0\.125"/);
  const ecr = readFileSync(new URL('../../infra/aws/gpu_ecr.tf', import.meta.url), 'utf8');
  assert.ok(ecr.includes('count                = var.enable_gpu_image_repository ? 1 : 0'));
  assert.ok(ecr.includes('image_tag_mutability = "IMMUTABLE"'));
});
