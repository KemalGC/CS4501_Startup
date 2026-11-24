// No AWS calls or credentials: enforce review-only GPU capacity defaults.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tf = readFileSync(new URL('../../infra/aws/gpu_capacity.tf', import.meta.url), 'utf8');
const vars = readFileSync(new URL('../../infra/aws/variables.tf', import.meta.url), 'utf8');
const outputs = readFileSync(new URL('../../infra/aws/outputs.tf', import.meta.url), 'utf8');
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
  assert.match(tf, /instance_type\s*=\s*var\.gpu_smoke_instance_type/);
  assert.match(tf, /requires_compatibilities\s*=\s*\["EC2"\]/);
  assert.match(tf, /value\s*=\s*local\.gpu_smoke_gpu_resource/);
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
  assert.match(tf, /value\s*=\s*local\.gpu_smoke_gpu_resource/);
  const ecr = readFileSync(new URL('../../infra/aws/gpu_ecr.tf', import.meta.url), 'utf8');
  assert.ok(ecr.includes('count                = var.enable_gpu_image_repository ? 1 : 0'));
  assert.ok(ecr.includes('image_tag_mutability = "IMMUTABLE"'));
});

test('reviewed GPU hosts select an official fixed AMI and a concrete template version', () => {
  const imageLookup = tf.split('data "aws_ami" "gpu_ecs" {')[1]?.split(/\n(?:data|resource) /)[0];
  assert.ok(imageLookup, 'the SSM image ID must be checked against EC2 AMI metadata');
  assert.match(imageLookup, /count\s*=\s*var\.enable_gpu \? 1 : 0/);
  assert.match(imageLookup, /owners\s*=\s*\["amazon"\]/);
  const filters = new Map([...imageLookup.matchAll(/filter\s*\{([\s\S]*?)\}/g)].map(([, block]) => [
    JSON.parse(block.match(/name\s*=\s*("[^"\n]+")/)[1]),
    block.match(/values\s*=\s*(\[[^\n]+\])/)[1],
  ]));
  assert.equal(filters.get('image-id'), '[nonsensitive(data.aws_ssm_parameter.gpu_ecs_ami[0].value)]');
  for (const [name, values] of Object.entries({
    name: ['al2023-ami-ecs-gpu-hvm-2023.0.*'], architecture: ['x86_64'],
    'virtualization-type': ['hvm'], 'root-device-type': ['ebs'], state: ['available'],
  })) {
    assert.deepEqual(JSON.parse(filters.get(name)), values, `AMI filter ${name}`);
  }

  // Exercise the release-name pattern and boundary used by the Terraform
  // postcondition. Names may include the official kernel/architecture suffix.
  const releaseGuard = imageLookup.match(/tonumber\(regex\(("(?:\\.|[^"\\])*"),\s*self\.name\)\[0\]\)\s*>=\s*(\d{8})/);
  assert.ok(releaseGuard, 'an AMI without the GRID userspace fix must fail before launch');
  const releasePattern = new RegExp(JSON.parse(releaseGuard[1]));
  const minimumRelease = Number(releaseGuard[2]);
  assert.ok(minimumRelease >= 20261119);
  const accepts = name => {
    const match = releasePattern.exec(name);
    return match !== null && Number(match[1]) >= minimumRelease;
  };
  assert.equal(accepts('al2023-ami-ecs-gpu-hvm-2023.0.20261118-x86_64-ebs'), false);
  assert.equal(accepts('al2023-ami-ecs-gpu-hvm-2023.0.20261119'), true);
  assert.equal(accepts('al2023-ami-ecs-gpu-hvm-2023.0.20261119-kernel-6.1-x86_64-ebs'), true);
  assert.equal(accepts('al2023-ami-ecs-gpu-hvm-2023.0.20270101-x86_64-ebs'), true);
  assert.equal(accepts('al2023-ami-ecs-hvm-2023.0.20261119-x86_64'), false);
  assert.equal(accepts('unofficial-al2023-ami-ecs-gpu-hvm-2023.0.20261119'), false);

  const group = tf.split('resource "aws_autoscaling_group" "gpu" {')[1].split('\nresource ')[0];
  assert.match(group, /version\s*=\s*tostring\(aws_launch_template\.gpu\[0\]\.latest_version\)/);
  assert.doesNotMatch(group, /version\s*=\s*"\$(Latest|Default)"/);
});

test('hardware is limited to two four-vCPU profiles with matching approval and task GPU units', () => {
  const hardware = vars.split('variable "gpu_smoke_instance_type" {')[1]?.split('\nvariable ')[0];
  assert.ok(hardware);
  assert.match(hardware, /default\s*=\s*"g6f\.xlarge"/);
  const allowed = hardware.match(/contains\((\[[^\n]+\]),\s*var\.gpu_smoke_instance_type\)/);
  assert.ok(allowed, 'the hardware selector must reject unsupported instances');
  assert.deepEqual(JSON.parse(allowed[1]), ['g6f.xlarge', 'g4dn.xlarge']);

  const gpuGuard = vars.split('variable "enable_gpu" {')[1].split('\nvariable ')[0];
  assert.match(gpuGuard, /var\.gpu_smoke_approval\s*==\s*\(var\.gpu_smoke_instance_type\s*==\s*"g4dn\.xlarge"\s*\?\s*"I_APPROVE_ONE_G4DN_SMOKE_INSTANCE"\s*:\s*"I_APPROVE_ONE_G6F_SMOKE_INSTANCE"\)/);

  const allocation = tf.match(/gpu_smoke_gpu_resources\s*=\s*\{([^}]+)\}/)?.[1];
  assert.ok(allocation);
  const gpuUnits = Object.fromEntries([...allocation.matchAll(/"([^"\n]+)"\s*=\s*"([^"\n]+)"/g)].map(([, type, units]) => [type, units]));
  assert.deepEqual(gpuUnits, { 'g6f.xlarge': '0.125', 'g4dn.xlarge': '1' });
  assert.match(tf, /gpu_smoke_gpu_resource\s*=\s*local\.gpu_smoke_gpu_resources\[var\.gpu_smoke_instance_type\]/);
  for (const name of ['gpu', 'gpu_preflight']) {
    const task = tf.split(`resource "aws_ecs_task_definition" "${name}" {`)[1].split('\nresource ')[0];
    assert.match(task, /resourceRequirements\s*=\s*\[\s*\{\s*type\s*=\s*"GPU",\s*value\s*=\s*local\.gpu_smoke_gpu_resource\s*\}/);
  }

  // Capacity-only targeted plans must refresh outputs from their managed
  // resources, not leave a direct variable output stale in the saved state.
  const typeOutput = outputs.split('output "gpu_smoke_instance_type" {')[1].split('\noutput ')[0];
  const unitsOutput = outputs.split('output "gpu_smoke_gpu_resource" {')[1].split('\noutput ')[0];
  const workerOutput = outputs.split('output "gpu_smoke_worker_task_definition" {')[1].split('\noutput ')[0];
  assert.match(typeOutput, /aws_launch_template\.gpu\[0\]\.instance_type/);
  assert.match(unitsOutput, /jsondecode\(aws_ecs_task_definition\.gpu_preflight\[0\]\.container_definitions\)/);
  assert.match(unitsOutput, /requirement\.value if requirement\.type == "GPU"/);
  assert.match(workerOutput, /aws_ecs_task_definition\.gpu\[0\]\.arn/);
});
