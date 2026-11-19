# AWS Batch/Fargate remains at zero running containers while the queue is idle.
# This stack intentionally creates NO GPU compute environment, NAT gateway,
# load balancer, or long-lived container service.
resource "aws_ecr_repository" "cpu_worker" {
  name                 = "${local.prefix}-cpu-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "cpu_worker" {
  repository = aws_ecr_repository.cpu_worker.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove stale untagged worker images after one week"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_security_group" "batch_jobs" {
  name_prefix            = "${local.prefix}-batch-"
  description            = "Outbound-only Fargate inference jobs; no inbound ports"
  vpc_id                 = local.vpc_id
  revoke_rules_on_delete = true

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "ECR, AWS APIs and model-package endpoints over public egress"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudwatch_log_group" "batch_jobs" {
  name              = "/aws/batch/${local.prefix}-cpu"
  retention_in_days = 14
}

resource "aws_batch_compute_environment" "cpu" {
  name_prefix = "${local.prefix}-cpu-"
  type        = "MANAGED"
  state       = "ENABLED"

  compute_resources {
    type               = "FARGATE"
    max_vcpus          = var.cpu_max_vcpus
    security_group_ids = [aws_security_group.batch_jobs.id]
    subnets            = local.subnet_ids
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_batch_job_queue" "cpu" {
  name = "${local.prefix}-cpu"
  # Smoke mode permits an operator to submit a single test job directly to
  # Batch while the public API's CPU_BATCH_JOB_QUEUE remains empty. Do not
  # conflate an enabled Batch queue with public submission authorization.
  state    = (var.enable_cpu_analysis || var.enable_cpu_smoke_queue) ? "ENABLED" : "DISABLED"
  priority = 10

  lifecycle {
    precondition {
      condition     = !var.enable_cpu_smoke_queue || var.cpu_max_vcpus == 2
      error_message = "CPU smoke testing must cap the compute environment at 2 vCPUs (one Fargate job)."
    }
    precondition {
      condition     = !(var.enable_cpu_smoke_queue && var.enable_cpu_analysis)
      error_message = "Operator-only smoke mode and public API submissions cannot be enabled together."
    }
    precondition {
      condition     = !(var.enable_cpu_analysis || var.enable_cpu_smoke_queue) || var.worker_image_tag != "cpu-latest"
      error_message = "Set worker_image_tag to the unique tag of a locally benchmarked ECR image before enabling CPU Batch."
    }
  }

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.cpu.arn
  }
}

# This definition references a worker image that must be built, benchmarked,
# security-reviewed and pushed BEFORE a successful apply. The S3 CPU adapter
# is implemented, but live ONNX inference has not been benchmarked on Fargate.
resource "aws_batch_job_definition" "cpu" {
  name                  = "${local.prefix}-cpu"
  type                  = "container"
  platform_capabilities = ["FARGATE"]
  propagate_tags        = true

  container_properties = jsonencode({
    image            = "${aws_ecr_repository.cpu_worker.repository_url}:${var.worker_image_tag}"
    command          = var.worker_command
    jobRoleArn       = aws_iam_role.cpu_job.arn
    executionRoleArn = aws_iam_role.batch_execution.arn
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" }
    ]
    fargatePlatformConfiguration = {
      platformVersion = "LATEST"
    }
    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.batch_jobs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "analysis"
      }
    }
    environment = [
      { name = "S3_BUCKET", value = aws_s3_bucket.media.bucket },
      { name = "JOBS_TABLE", value = aws_dynamodb_table.jobs.name },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      { name = "STROKESENSE_ANALYSIS_TIMEOUT_SECONDS", value = "3300" }
    ]
  })

  retry_strategy {
    attempts = 1
  }

  timeout {
    attempt_duration_seconds = var.cpu_job_timeout_seconds
  }
}
