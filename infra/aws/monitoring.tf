# Required email subscription; SNS alarm email delivery begins only after the
# recipient confirms the AWS SNS subscription. No always-running compute.
resource "aws_sns_topic" "ops" {
  name = "${local.prefix}-ops"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.ops.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.prefix}-api-errors"
  alarm_description   = "Any HTTP API Lambda invocation errors in five minutes"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  alarm_actions       = [aws_sns_topic.ops.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name          = "${local.prefix}-api-throttles"
  alarm_description   = "Lambda API concurrency ceiling has been reached"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  alarm_actions       = [aws_sns_topic.ops.arn]
}

# The Python handler deliberately catches errors and returns HTTP 503; these
# are successful Lambda invocations, so Lambda Errors alone cannot detect them.
resource "aws_cloudwatch_metric_alarm" "http_api_5xx" {
  alarm_name          = "${local.prefix}-http-5xx"
  alarm_description   = "API returned server errors, including caught Lambda exceptions"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { ApiId = aws_apigatewayv2_api.public.id }
  alarm_actions       = [aws_sns_topic.ops.arn]
}

# Alerts on Batch failures; the independent scheduled Lambda in
# reconciliation.tf performs actual quota reconciliation. An EventBridge
# notification is not itself a refund.
resource "aws_cloudwatch_event_rule" "batch_failed" {
  name        = "${local.prefix}-cpu-failures"
  description = "Notify when a CPU Batch job fails"
  event_pattern = jsonencode({
    source        = ["aws.batch"]
    "detail-type" = ["Batch Job State Change"]
    detail = {
      status   = ["FAILED"]
      jobQueue = [aws_batch_job_queue.cpu.arn]
    }
  })
}

resource "aws_cloudwatch_event_target" "batch_failed" {
  rule      = aws_cloudwatch_event_rule.batch_failed.name
  target_id = "NotifyOperator"
  arn       = aws_sns_topic.ops.arn
}

data "aws_iam_policy_document" "sns_events" {
  statement {
    sid       = "AllowAccountAdministration"
    actions   = ["SNS:*"]
    resources = [aws_sns_topic.ops.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.ops.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.batch_failed.arn]
    }
  }

  # Alarm actions call SNS as the CloudWatch service principal. Without this
  # explicit grant, the alarm can enter ALARM but email delivery can fail.
  statement {
    sid       = "AllowOnlyStrokeSenseCloudWatchAlarms"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.ops.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_metric_alarm.lambda_errors.arn,
        aws_cloudwatch_metric_alarm.lambda_throttles.arn,
        aws_cloudwatch_metric_alarm.http_api_5xx.arn,
        aws_cloudwatch_metric_alarm.reconcile_errors.arn,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "allow_events" {
  arn    = aws_sns_topic.ops.arn
  policy = data.aws_iam_policy_document.sns_events.json
}

# Budget alerts are advisory, not spend enforcement. This budget deliberately
# covers the entire AWS account; AWS cost-allocation tags need activation to
# create a trustworthy project-only budget later.
resource "aws_budgets_budget" "account_alert" {
  name         = "${local.prefix}-account-monthly-alert"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Track pre-credit usage. Otherwise the $100 promotional credit could hide
  # accumulating Fargate/S3 charges until the credit is exhausted.
  cost_types {
    include_credit = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
}
