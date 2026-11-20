# Paid GPU queue infrastructure — deliberately INERT unless explicitly provisioned.
#
# This creates no GPU compute. By default count=0 for every resource.
# Even after opting into the queue scaffold, the Lambda event mapping stays
# DISABLED and its runtime gate GPU_DISPATCH_ENABLED remains false.
# The IAM role has NO ecs:RunTask or iam:PassRole permissions. A separate,
# reviewed PR must implement and approve those before dispatch can run.

resource "aws_sqs_queue" "gpu_dead_letter" {
  count                      = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name                       = "${local.prefix}-paid-gpu-dead-letter.fifo"
  fifo_queue                 = true
  sqs_managed_sse_enabled    = true
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 180
}

resource "aws_sqs_queue" "gpu_jobs" {
  count                       = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name                        = "${local.prefix}-paid-gpu-jobs.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  sqs_managed_sse_enabled     = true
  message_retention_seconds   = 604800
  visibility_timeout_seconds  = 180
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.gpu_dead_letter[0].arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "gpu_dead_letter" {
  count     = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  queue_url = aws_sqs_queue.gpu_dead_letter[0].id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.gpu_jobs[0].arn]
  })
}

resource "aws_iam_role" "gpu_dispatcher" {
  count              = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name               = "${local.prefix}-gpu-queue-dispatcher"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "gpu_dispatcher_logs" {
  count      = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  role       = aws_iam_role.gpu_dispatcher[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "gpu_dispatcher" {
  count = var.enable_paid_gpu_queue_scaffold ? 1 : 0

  statement {
    sid       = "ReceiveOnlyDedicatedPaidGpuQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.gpu_jobs[0].arn]
  }

  statement {
    sid       = "ReadAndUpdateOnlyPaidGpuJobState"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }

  statement {
    sid       = "HoldOneDedicatedGpuJobSlot"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.users.arn]
  }

  # NO ecs:RunTask or iam:PassRole here. Until an approved GPU capacity
  # provider/task/worker role exists the queue cannot launch compute.
}

resource "aws_iam_role_policy" "gpu_dispatcher" {
  count  = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name   = "${local.prefix}-gpu-dispatcher-inert-policy"
  role   = aws_iam_role.gpu_dispatcher[0].id
  policy = data.aws_iam_policy_document.gpu_dispatcher[0].json
}

resource "aws_cloudwatch_log_group" "gpu_dispatcher" {
  count             = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name              = "/aws/lambda/${local.prefix}-gpu-dispatcher"
  retention_in_days = 14
}

resource "aws_lambda_function" "gpu_dispatcher" {
  count            = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  function_name    = "${local.prefix}-gpu-dispatcher"
  role             = aws_iam_role.gpu_dispatcher[0].arn
  handler          = "aws_app.gpu_queue_handler.lambda_handler"
  filename         = local.lambda_zip_path
  source_code_hash = try(filebase64sha256(local.lambda_zip_path), null)
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      S3_BUCKET                 = aws_s3_bucket.media.bucket
      USERS_TABLE               = aws_dynamodb_table.users.name
      JOBS_TABLE                = aws_dynamodb_table.jobs.name
      GPU_DISPATCH_ENABLED      = "false"
      PAID_BILLING_ENABLED      = "false"
      PAID_GPU_ENABLED          = "false"
      GPU_DISPATCH_READY        = "false"
      GPU_SQS_SOURCE_ARN        = aws_sqs_queue.gpu_jobs[0].arn
      GPU_ECS_CLUSTER           = try(aws_ecs_cluster.gpu[0].arn, "")
      GPU_ECS_TASK_DEFINITION   = try(aws_ecs_task_definition.gpu[0].arn, "")
      GPU_ECS_CAPACITY_PROVIDER = try(aws_ecs_capacity_provider.gpu[0].name, "")
      GPU_SUBNET_IDS            = var.enable_gpu ? var.gpu_subnet_id : ""
      GPU_SECURITY_GROUP_IDS    = try(aws_security_group.gpu_task[0].id, "")
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.gpu_dispatcher_logs,
    aws_iam_role_policy.gpu_dispatcher,
    aws_cloudwatch_log_group.gpu_dispatcher,
  ]
}

resource "aws_lambda_event_source_mapping" "gpu_dispatcher" {
  count                   = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  event_source_arn        = aws_sqs_queue.gpu_jobs[0].arn
  function_name           = aws_lambda_function.gpu_dispatcher[0].arn
  enabled                 = false
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  depends_on              = [aws_iam_role_policy.gpu_dispatcher]
}
