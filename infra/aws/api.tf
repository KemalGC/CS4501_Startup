locals {
  lambda_zip_path = startswith(var.api_lambda_zip_path, "/") ? var.api_lambda_zip_path : "${path.module}/${var.api_lambda_zip_path}"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.prefix}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name                  = "${local.prefix}-api"
  role                           = aws_iam_role.api.arn
  handler                        = var.api_lambda_handler
  filename                       = local.lambda_zip_path
  source_code_hash               = try(filebase64sha256(local.lambda_zip_path), null)
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  memory_size                    = 512
  timeout                        = 25
  reserved_concurrent_executions = var.api_reserved_concurrency

  environment {
    variables = {
      S3_BUCKET                          = aws_s3_bucket.media.bucket
      USERS_TABLE                        = aws_dynamodb_table.users.name
      JOBS_TABLE                         = aws_dynamodb_table.jobs.name
      ADMIN_AUDIT_TABLE                  = aws_dynamodb_table.admin_access_audit.name
      ADMIN_COGNITO_SUBS                 = join(",", var.admin_cognito_subs)
      ADMIN_AUDIT_TTL_DAYS               = tostring(var.admin_audit_retention_days)
      FEEDBACK_TABLE                     = aws_dynamodb_table.feedback.name
      CPU_BATCH_JOB_QUEUE                = var.enable_cpu_analysis ? aws_batch_job_queue.cpu.arn : ""
      CPU_BATCH_JOB_DEFINITION           = aws_batch_job_definition.cpu.arn
      CPU_GLOBAL_DAILY_LIMIT             = tostring(var.cpu_global_daily_limit)
      CPU_GLOBAL_MONTHLY_LIMIT           = tostring(var.cpu_global_monthly_limit)
      AWS_S3_US_EAST_1_REGIONAL_ENDPOINT = "regional"
      FREE_LIFETIME_BYTES                = tostring(var.free_lifetime_bytes)
      FREE_MAX_VIDEO_BYTES               = tostring(var.free_max_video_bytes)
      PAID_MAX_VIDEO_BYTES               = tostring(var.paid_max_video_bytes)
      FREE_REPORT_TTL_SECONDS            = tostring(var.free_report_ttl_days * 86400)
      PAID_REPORT_TTL_SECONDS            = tostring(var.paid_report_ttl_days * 86400)
      RAW_UPLOAD_TTL_SECONDS             = tostring(var.raw_upload_ttl_days * 86400)
      TERMINAL_RECORD_GRACE_SECONDS      = tostring(var.terminal_job_record_grace_days * 86400)
      PAID_BILLING_ENABLED               = "false"
      PAID_GPU_ENABLED                   = "false"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.api_logs, aws_cloudwatch_log_group.api]
}

resource "aws_apigatewayv2_api" "public" {
  name          = "${local.prefix}-http"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.allowed_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 600
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.public.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.public.id
  authorizer_type  = "JWT"
  name             = "${local.prefix}-cognito"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
  }
}

# These routes are all protected, including report links. The app validates
# record ownership and signs a short-lived S3 URL only for the right user.
locals {
  authenticated_routes = toset([
    "POST /uploads/start",
    "POST /uploads/part",
    "POST /uploads/complete",
    "POST /uploads/abort",
    "POST /analysis/jobs",
    "GET /analysis/jobs",
    "GET /analysis/jobs/{id}",
    "POST /analysis/jobs/{id}/review",
    "GET /admin/jobs",
    "GET /admin/videos/{id}",
    "GET /reports/{id}",
    "GET /reports/{id}/artifacts",
  ])
}

resource "aws_apigatewayv2_route" "authenticated" {
  for_each           = local.authenticated_routes
  api_id             = aws_apigatewayv2_api.public.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.public.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Explicit public route: no Cognito account is required to rate site usability.
# Lambda validates a tiny JSON schema and caps daily writes transactionally.
resource "aws_apigatewayv2_route" "feedback" {
  api_id             = aws_apigatewayv2_api.public.id
  route_key          = "POST /feedback"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.public.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 40
    throttling_rate_limit  = 20
  }

  route_settings {
    route_key              = aws_apigatewayv2_route.feedback.route_key
    throttling_burst_limit = 4
    throttling_rate_limit  = 1
  }
}

resource "aws_lambda_permission" "gateway" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.public.execution_arn}/*/*"
}
