# Milestone 2C: review-only, cost-bounded ECS EC2 GPU capacity blueprint.
# Default remains count=0. enable_gpu is only allowed in a separately
# acknowledged operator-only GPU smoke mode, which disables paid dispatch,
# billing and ECS automatic scaling. See GPU_SMOKE_M3.md before ANY apply.

resource "aws_ecs_cluster" "gpu" {
  count = var.enable_gpu ? 1 : 0
  name  = format("%s-paid-gpu", local.prefix)
}

data "aws_ssm_parameter" "gpu_ecs_ami" {
  count = var.enable_gpu ? 1 : 0
  name  = "/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id"
}

data "aws_iam_policy_document" "gpu_ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gpu_ec2_instance" {
  count              = var.enable_gpu ? 1 : 0
  name               = format("ecsInstanceRole-%s-gpu", local.prefix)
  assume_role_policy = data.aws_iam_policy_document.gpu_ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "gpu_ec2_instance" {
  count      = var.enable_gpu ? 1 : 0
  role       = aws_iam_role.gpu_ec2_instance[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "gpu_ec2" {
  count = var.enable_gpu ? 1 : 0
  name  = format("%s-gpu-instance", local.prefix)
  role  = aws_iam_role.gpu_ec2_instance[0].name
}

resource "aws_security_group" "gpu_instance" {
  count                  = var.enable_gpu ? 1 : 0
  name_prefix            = format("%s-gpu-instance-", local.prefix)
  description            = "No incoming ports; only EC2 host performs image pulls"
  vpc_id                 = local.vpc_id
  revoke_rules_on_delete = true

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "ECS agent, ECR pull, logging and operating system services"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "gpu_task" {
  count                  = var.enable_gpu ? 1 : 0
  name_prefix            = format("%s-gpu-task-", local.prefix)
  description            = "No inbound or public IP; TLS to S3 through VPC gateway endpoint"
  vpc_id                 = local.vpc_id
  revoke_rules_on_delete = true

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "S3 HTTPS via the subnet route table gateway endpoint"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ECS EC2 awsvpc task ENIs cannot receive public IPv4 addresses. Real-data GPU
# workers reach S3 through a gateway endpoint in the GPU subnet's route table;
# there is no NAT gateway or long-lived worker service here.
#
# The blank-input CUDA preflight needs no S3 (the EC2 host's ECS agent pulls
# the image and ships logs over the host ENI). In aws-dev the only route table
# is the VPC main table, implicitly used by every default subnet including the
# live CPU Batch analyzer; adding an endpoint there would re-route all of its
# S3 traffic. So smoke mode creates no endpoint; non-smoke GPU requires one
# (enforced on the paid worker task definition below).
resource "aws_vpc_endpoint" "gpu_s3" {
  count             = var.enable_gpu && !var.gpu_smoke_mode ? 1 : 0
  vpc_id            = local.vpc_id
  service_name      = format("com.amazonaws.%s.s3", var.aws_region)
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.gpu_s3_route_table_ids

  lifecycle {
    precondition {
      condition     = length(var.gpu_s3_route_table_ids) >= 1
      error_message = "Select/review the GPU subnet S3 gateway route table before provisioning."
    }
  }
}

resource "aws_launch_template" "gpu" {
  count         = var.enable_gpu ? 1 : 0
  name_prefix   = format("%s-gpu-", local.prefix)
  image_id      = data.aws_ssm_parameter.gpu_ecs_ami[0].value
  instance_type = "g6f.xlarge" # Fixed: 4 vCPU, 16 GiB RAM, 0.125 L4 / 3 GB VRAM
  ebs_optimized = true

  # Bounded boot/image cache space for CUDA/ONNX video processing.
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 80
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  iam_instance_profile {
    arn = aws_iam_instance_profile.gpu_ec2[0].arn
  }

  network_interfaces {
    device_index                = 0
    associate_public_ip_address = true # EC2 host only; ECS task remains private
    security_groups             = [aws_security_group.gpu_instance[0].id]
    delete_on_termination       = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  user_data = base64encode(join("\n", [
    "#!/bin/bash",
    format("echo ECS_CLUSTER=%s >> /etc/ecs/ecs.config", aws_ecs_cluster.gpu[0].name),
    "echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config",
    # awsvpc tasks must not reach IMDS and borrow the host instance-profile role.
    "echo ECS_AWSVPC_BLOCK_IMDS=true >> /etc/ecs/ecs.config",
    "",
  ]))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = format("%s-gpu-review-only", local.prefix) }
  }
}

resource "aws_autoscaling_group" "gpu" {
  count    = var.enable_gpu ? 1 : 0
  name     = format("%s-gpu-one-instance", local.prefix)
  min_size = 0
  # Smoke: idle at max 0; the operator script raises max to 1 for one attempt
  # and returns it to 0, so a later ordinary apply cannot re-arm capacity.
  max_size         = var.gpu_smoke_mode ? 0 : 1
  desired_capacity = 0
  # Smoke mode must allow explicit operator shutdown of the instance.
  protect_from_scale_in = !var.gpu_smoke_mode
  health_check_type     = "EC2"
  vpc_zone_identifier   = [var.gpu_subnet_id]
  # Smoke: an unhealthy or rebalanced host must not silently become a second
  # paid instance. Launch is additionally suspended by the script once the
  # single host exists. Terminate and ScheduledActions stay active.
  suspended_processes = var.gpu_smoke_mode ? ["AZRebalance", "ReplaceUnhealthy"] : []

  launch_template {
    id      = aws_launch_template.gpu[0].id
    version = "$Latest"
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity]
    precondition {
      condition     = can(regex("^subnet-[0-9a-f]{8,17}$", var.gpu_subnet_id))
      error_message = "Select an existing, reviewed public GPU subnet (with host public-IP support)."
    }
  }
}

resource "aws_ecs_capacity_provider" "gpu" {
  count = var.enable_gpu ? 1 : 0
  name  = format("%s-gpu-asg", local.prefix)

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.gpu[0].arn
    managed_termination_protection = var.gpu_smoke_mode ? "DISABLED" : "ENABLED"
    # Managed draining adds an ASG termination lifecycle hook that can hold a
    # host while a standalone task runs; disposable smoke capacity skips it.
    managed_draining = var.gpu_smoke_mode ? "DISABLED" : "ENABLED"

    managed_scaling {
      status                    = var.gpu_smoke_mode ? "DISABLED" : "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 1
      instance_warmup_period    = 180
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "gpu" {
  count              = var.enable_gpu ? 1 : 0
  cluster_name       = aws_ecs_cluster.gpu[0].name
  capacity_providers = [aws_ecs_capacity_provider.gpu[0].name]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.gpu[0].name
    weight            = 1
  }
}

resource "aws_iam_role" "gpu_worker" {
  count              = var.enable_gpu ? 1 : 0
  name               = format("%s-gpu-worker", local.prefix)
  assume_role_policy = data.aws_iam_policy_document.ecs_task_trust.json
}

data "aws_iam_policy_document" "gpu_worker" {
  count = var.enable_gpu ? 1 : 0

  statement {
    sid       = "ReadUploadedVideosOnly"
    actions   = ["s3:GetObject"]
    resources = [format("%s/uploads/*", aws_s3_bucket.media.arn)]
  }
  statement {
    sid       = "WritePaidReportsOnly"
    actions   = ["s3:PutObject"]
    resources = [format("%s/reports/paid/*", aws_s3_bucket.media.arn)]
  }
}

resource "aws_iam_role_policy" "gpu_worker" {
  count  = var.enable_gpu ? 1 : 0
  name   = format("%s-gpu-private-s3", local.prefix)
  role   = aws_iam_role.gpu_worker[0].id
  policy = data.aws_iam_policy_document.gpu_worker[0].json
}

resource "aws_cloudwatch_log_group" "gpu_worker" {
  count             = var.enable_gpu ? 1 : 0
  name              = format("/ecs/%s/paid-gpu", local.prefix)
  retention_in_days = 14
}

# No tag-based image references: the digest must be reviewed and immutable.
# This task is EC2-specific (NOT MANAGED_INSTANCES and NOT Fargate).
resource "aws_ecs_task_definition" "gpu" {
  count                    = var.enable_gpu ? 1 : 0
  family                   = format("%s-paid-gpu", local.prefix)
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  cpu                      = "2048"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.batch_execution.arn
  task_role_arn            = aws_iam_role.gpu_worker[0].arn

  container_definitions = jsonencode([
    {
      name      = "paid-gpu-worker"
      image     = var.gpu_worker_image_uri
      essential = true
      cpu       = 2048
      memory    = 8192
      command   = ["python3", "-m", "aws_app.gpu_worker"]
      resourceRequirements = [
        { type = "GPU", value = "0.125" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.gpu_worker[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "analysis"
        }
      }
    }
  ])

  lifecycle {
    precondition {
      condition     = can(regex("@sha256:[a-f0-9]{64}$", var.gpu_worker_image_uri))
      error_message = "GPU task image must be an operator-reviewed, ECR digest-pinned image."
    }
    precondition {
      condition     = var.gpu_smoke_mode || length(var.gpu_s3_route_table_ids) >= 1
      error_message = "Real-data GPU workers need a reviewed GPU-subnet S3 gateway route table."
    }
  }

  depends_on = [aws_iam_role_policy.gpu_worker]
}

# This isolated grant exists only when both currently-disabled safety gates
# are enabled. It is intentionally not on the API/reconciler roles.
data "aws_iam_policy_document" "gpu_dispatch_launch" {
  count = var.enable_gpu && var.enable_paid_gpu_queue_scaffold ? 1 : 0

  statement {
    sid       = "DescribeReviewedTaskDefinition"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }
  statement {
    sid       = "RunOnlyReviewedGpuTaskInIsolatedCluster"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.gpu[0].arn]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.gpu[0].arn]
    }
  }
  statement {
    sid       = "PassOnlyGpuTaskAndExistingExecutionRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.gpu_worker[0].arn, aws_iam_role.batch_execution.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "gpu_dispatch_launch" {
  count  = var.enable_gpu && var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name   = format("%s-gpu-approved-launch-only", local.prefix)
  role   = aws_iam_role.gpu_dispatcher[0].id
  policy = data.aws_iam_policy_document.gpu_dispatch_launch[0].json
}

# Smoke task uses the same reviewed CUDA image but requires no customer data
# or GPU worker entitlement. Run manually once, then STOP and scale ASG to 0.
resource "aws_ecs_task_definition" "gpu_preflight" {
  count                    = var.enable_gpu && var.gpu_smoke_mode ? 1 : 0
  family                   = format("%s-gpu-preflight", local.prefix)
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  cpu                      = "2048"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.batch_execution.arn

  container_definitions = jsonencode([
    {
      name      = "gpu-preflight"
      image     = var.gpu_worker_image_uri
      essential = true
      cpu       = 2048
      memory    = 8192
      command   = ["python3", "-m", "aws_app.gpu_preflight", "--model", "/app/models/yolo11n-pose.onnx"]
      resourceRequirements = [
        { type = "GPU", value = "0.125" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.gpu_worker[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "gpu-preflight"
        }
      }
    }
  ])
  lifecycle {
    precondition {
      condition     = can(regex("@sha256:[a-f0-9]{64}$", var.gpu_worker_image_uri))
      error_message = "Pin the reviewed CUDA worker image by ECR sha256 digest before GPU smoke launch."
    }
  }
}
