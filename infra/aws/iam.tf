data "aws_iam_policy_document" "ecs_task_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_execution" {
  name               = "${local.prefix}-batch-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_trust.json
}

resource "aws_iam_role_policy_attachment" "batch_execution" {
  role       = aws_iam_role.batch_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "cpu_job" {
  name               = "${local.prefix}-cpu-job"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_trust.json
}

# The worker can read its input and write its report, but cannot list media
# across users, alter identity/entitlement data, or submit additional jobs.
data "aws_iam_policy_document" "cpu_job" {
  statement {
    sid       = "ReadInputVideos"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/uploads/*"]
  }

  statement {
    sid       = "WriteReports"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.media.arn}/reports/*"]
  }

  statement {
    sid       = "ReadAndUpdateOwnJobRecord"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
}

resource "aws_iam_role_policy" "cpu_job" {
  name   = "${local.prefix}-cpu-data"
  role   = aws_iam_role.cpu_job.id
  policy = data.aws_iam_policy_document.cpu_job.json
}

resource "aws_iam_role" "api" {
  name               = "${local.prefix}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Uploads/analysis/reports are authorized through Cognito JWT at API Gateway.
# Only GET /health and rate-limited POST /feedback are public routes. The
# Lambda separately checks Cognito sub against user records and S3 keys.
data "aws_iam_policy_document" "api" {
  statement {
    sid = "ReadWriteQuotaAndJobs"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:TransactWriteItems", "dynamodb:ConditionCheckItem"
    ]
    resources = [aws_dynamodb_table.users.arn, aws_dynamodb_table.jobs.arn]
  }

  statement {
    sid       = "QueryOwnedJobsIndex"
    actions   = ["dynamodb:Query"]
    resources = ["${aws_dynamodb_table.jobs.arn}/index/user_id-created_at-index"]
  }

  statement {
    sid       = "SubmitAnonymousWebsiteFeedbackOnly"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.feedback.arn]

    # DynamoDB checks the IAM permissions of underlying Put/Update operations
    # inside TransactWriteItems. No direct, nontransactional feedback writes.
    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "dynamodb:EnclosingOperation"
      values   = ["TransactWriteItems"]
    }
  }

  statement {
    sid = "ManagePrivateVideoUploads"
    actions = [
      "s3:PutObject", "s3:GetObject", "s3:DeleteObject",
      "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
    ]
    resources = ["${aws_s3_bucket.media.arn}/uploads/*"]
  }

  statement {
    sid       = "PresignPrivateReportDownloads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/reports/*"]
  }

  # S3 HeadObject returns 403 instead of 404 for a missing report unless the
  # caller also has ListBucket. The API must distinguish an absent report from
  # a transient permission/storage failure before settling user quota.
  statement {
    sid       = "DistinguishMissingReportFromAccessFailure"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
  }

  statement {
    sid       = "SubmitApprovedCpuJobsOnly"
    actions   = ["batch:SubmitJob"]
    resources = [aws_batch_job_queue.cpu.arn, aws_batch_job_definition.cpu.arn]
  }

  statement {
    sid       = "ReadExecutionStateByAwsJobId"
    actions   = ["batch:DescribeJobs"]
    resources = ["*"]
  }

  statement {
    sid       = "PassOnlyWorkerRolesToBatch"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.cpu_job.arn, aws_iam_role.batch_execution.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${local.prefix}-api-data"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}
