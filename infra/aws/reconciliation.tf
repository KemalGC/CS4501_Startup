# Reconciles expiring uploads and completed Batch jobs independently of the
# browser. This removes the failure mode where a user closes the page before
# status polling can refund a failed job's reserved lifetime quota.
#
# Zero running compute while idle: EventBridge invokes one short-lived Lambda
# every 15 minutes. It processes at most 25 due records per state per run.

data "aws_iam_policy_document" "reconcile_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "reconcile" {
  name               = "${local.prefix}-reconcile"
  assume_role_policy = data.aws_iam_policy_document.reconcile_trust.json
}

resource "aws_iam_role_policy_attachment" "reconcile_logs" {
  role       = aws_iam_role.reconcile.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "reconcile" {
  statement {
    sid = "ReadDueJobsAndSettleQuotaAtomically"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem",
      "dynamodb:TransactWriteItems",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [
      aws_dynamodb_table.users.arn,
      aws_dynamodb_table.jobs.arn,
      "${aws_dynamodb_table.jobs.arn}/index/status-expires_at-index",
    ]
  }

  statement {
    sid = "CheckOrRemoveExpiredPrivateMedia"
    actions = [
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = [
      "${aws_s3_bucket.media.arn}/uploads/*",
      "${aws_s3_bucket.media.arn}/reports/*",
    ]
  }

  # A missing report must return 404 to HeadObject, not the ambiguous 403
  # that S3 returns when ListBucket is absent. This prevents a false success
  # or an indefinitely unreconciled failed analysis.
  statement {
    sid       = "IdentifyMissingReports"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
  }

  statement {
    sid       = "CheckBatchTerminalStatus"
    actions   = ["batch:DescribeJobs"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "reconcile" {
  name   = "${local.prefix}-reconcile-quota"
  role   = aws_iam_role.reconcile.id
  policy = data.aws_iam_policy_document.reconcile.json
}

resource "aws_cloudwatch_log_group" "reconcile" {
  name              = "/aws/lambda/${local.prefix}-reconcile"
  retention_in_days = 14
}

resource "aws_lambda_function" "reconcile" {
  function_name                  = "${local.prefix}-reconcile"
  role                           = aws_iam_role.reconcile.arn
  handler                        = "aws_app.reconcile.lambda_handler"
  filename                       = local.lambda_zip_path
  source_code_hash               = try(filebase64sha256(local.lambda_zip_path), null)
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  memory_size                    = 256
  timeout                        = 120
  reserved_concurrent_executions = var.reconcile_reserved_concurrency

  environment {
    variables = {
      S3_BUCKET                          = aws_s3_bucket.media.bucket
      USERS_TABLE                        = aws_dynamodb_table.users.name
      JOBS_TABLE                         = aws_dynamodb_table.jobs.name
      CPU_BATCH_JOB_QUEUE                = aws_batch_job_queue.cpu.arn
      CPU_BATCH_JOB_DEFINITION           = aws_batch_job_definition.cpu.arn
      AWS_S3_US_EAST_1_REGIONAL_ENDPOINT = "regional"
      FREE_LIFETIME_BYTES                = tostring(var.free_lifetime_bytes)
      FREE_MAX_VIDEO_BYTES               = tostring(var.free_max_video_bytes)
      PAID_MAX_VIDEO_BYTES               = tostring(var.paid_max_video_bytes)
      FREE_REPORT_TTL_SECONDS            = tostring(var.free_report_ttl_days * 86400)
      PAID_REPORT_TTL_SECONDS            = tostring(var.paid_report_ttl_days * 86400)
      PAID_BILLING_ENABLED               = "false"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.reconcile_logs, aws_cloudwatch_log_group.reconcile]
}

resource "aws_cloudwatch_event_rule" "reconcile" {
  name                = "${local.prefix}-reconcile-15m"
  description         = "Settle completed analysis jobs and refund expired upload reservations"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "reconcile" {
  rule      = aws_cloudwatch_event_rule.reconcile.name
  target_id = "ReconcileQuota"
  arn       = aws_lambda_function.reconcile.arn

  retry_policy {
    maximum_event_age_in_seconds = 900
    maximum_retry_attempts       = 2
  }
}

resource "aws_lambda_permission" "reconcile_schedule" {
  statement_id  = "AllowScheduledReconciliation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reconcile.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reconcile.arn
}

resource "aws_cloudwatch_metric_alarm" "reconcile_errors" {
  alarm_name          = "${local.prefix}-reconcile-errors"
  alarm_description   = "Reconciler encountered an error; orphaned quota may require inspection"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.reconcile.function_name }
  alarm_actions       = [aws_sns_topic.ops.arn]
}
