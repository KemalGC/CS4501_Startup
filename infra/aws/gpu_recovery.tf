# Disabled paid GPU outbox and lifecycle reconciler. NO GPU capacity provisioned.
# All resources are count=0 by default through the existing scaffold switch.
# Even if the inert scaffold is approved separately, the EventBridge rule is
# DISABLED and the reconciler's runtime flag remains explicitly false.

resource "aws_iam_role" "gpu_reconcile" {
  count              = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name               = "${local.prefix}-gpu-reconcile"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "gpu_reconcile_logs" {
  count      = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  role       = aws_iam_role.gpu_reconcile[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "gpu_reconcile" {
  count = var.enable_paid_gpu_queue_scaffold ? 1 : 0

  statement {
    sid = "ReadStrongJobsAndSettlePaidCredits"
    actions = [
      "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem",
      "dynamodb:TransactWriteItems", "dynamodb:ConditionCheckItem",
    ]
    resources = [
      aws_dynamodb_table.jobs.arn,
      aws_dynamodb_table.users.arn,
      "${aws_dynamodb_table.jobs.arn}/index/status-expires_at-index",
    ]
  }

  statement {
    sid       = "RequeueOnlyPaidGpuJobs"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.gpu_jobs[0].arn]
  }

  statement {
    sid       = "DescribeGpuTaskStateOnly"
    actions   = ["ecs:DescribeTasks"]
    resources = ["*"]
  }

  statement {
    sid       = "CheckOnlyPrivateReportCompletion"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/reports/paid/*"]
  }

  statement {
    sid       = "DistinguishMissingPaidReports"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
  }

  # Do not grant ECS RunTask, StopTask, iam:PassRole, or subscription writes.
}

resource "aws_iam_role_policy" "gpu_reconcile" {
  count  = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name   = "${local.prefix}-gpu-reconcile-inert-data"
  role   = aws_iam_role.gpu_reconcile[0].id
  policy = data.aws_iam_policy_document.gpu_reconcile[0].json
}

resource "aws_cloudwatch_log_group" "gpu_reconcile" {
  count             = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name              = "/aws/lambda/${local.prefix}-gpu-reconcile"
  retention_in_days = 14
}

resource "aws_cloudwatch_event_rule" "gpu_reconcile" {
  count               = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  name                = "${local.prefix}-gpu-reconcile-15m"
  description         = "Disabled by default: future GPU outbox/task status cleanup"
  schedule_expression = "rate(15 minutes)"
  state               = "DISABLED"
}

resource "aws_lambda_function" "gpu_reconcile" {
  count            = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  function_name    = "${local.prefix}-gpu-reconcile"
  role             = aws_iam_role.gpu_reconcile[0].arn
  handler          = "aws_app.gpu_recovery.lambda_handler"
  filename         = local.lambda_zip_path
  source_code_hash = try(filebase64sha256(local.lambda_zip_path), null)
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      S3_BUCKET                 = aws_s3_bucket.media.bucket
      USERS_TABLE               = aws_dynamodb_table.users.name
      JOBS_TABLE                = aws_dynamodb_table.jobs.name
      GPU_RECONCILE_ENABLED     = "false"
      GPU_RECONCILE_RULE_ARN    = aws_cloudwatch_event_rule.gpu_reconcile[0].arn
      GPU_SQS_QUEUE_URL         = aws_sqs_queue.gpu_jobs[0].id
      PAID_BILLING_ENABLED      = "false"
      PAID_GPU_ENABLED          = "false"
      GPU_DISPATCH_READY        = "false"
      GPU_ECS_CLUSTER           = try(aws_ecs_cluster.gpu[0].arn, "")
      GPU_ECS_TASK_DEFINITION   = try(aws_ecs_task_definition.gpu[0].arn, "")
      GPU_ECS_CAPACITY_PROVIDER = try(aws_ecs_capacity_provider.gpu[0].name, "")
      GPU_SUBNET_IDS            = var.enable_gpu ? var.gpu_subnet_id : ""
      GPU_SECURITY_GROUP_IDS    = try(aws_security_group.gpu_task[0].id, "")
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.gpu_reconcile_logs,
    aws_iam_role_policy.gpu_reconcile,
    aws_cloudwatch_log_group.gpu_reconcile,
  ]
}

resource "aws_cloudwatch_event_target" "gpu_reconcile" {
  count     = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  rule      = aws_cloudwatch_event_rule.gpu_reconcile[0].name
  target_id = "DisabledGpuReconcile"
  arn       = aws_lambda_function.gpu_reconcile[0].arn
}

resource "aws_lambda_permission" "gpu_reconcile_schedule" {
  count         = var.enable_paid_gpu_queue_scaffold ? 1 : 0
  statement_id  = "AllowOnlyGpuReconcileRuleInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.gpu_reconcile[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gpu_reconcile[0].arn
}
