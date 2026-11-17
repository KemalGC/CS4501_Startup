output "aws_region" {
  value       = var.aws_region
  description = "AWS deployment region (development only)."
}

output "api_base_url" {
  value       = aws_apigatewayv2_api.public.api_endpoint
  description = "Use as the Vercel development frontend API base URL."
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "cognito_user_pool_client_id" {
  value       = aws_cognito_user_pool_client.web.id
  description = "Public OAuth web app client ID (never a client secret)."
}

output "cognito_domain" {
  value       = "https://${aws_cognito_user_pool_domain.login.domain}.auth.${var.aws_region}.amazoncognito.com"
  description = "Classic hosted UI domain for Cognito Google auth-code/PKCE sign-in."
}

output "google_oauth_redirect_uri" {
  value       = "https://${aws_cognito_user_pool_domain.login.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/idpresponse"
  description = "Paste verbatim in Google OAuth Authorized redirect URIs."
}

output "s3_media_bucket" {
  value = aws_s3_bucket.media.bucket
}

output "dynamodb_users_table" {
  value = aws_dynamodb_table.users.name
}

output "dynamodb_jobs_table" {
  value = aws_dynamodb_table.jobs.name
}

output "cpu_batch_queue_arn" {
  value = aws_batch_job_queue.cpu.arn
}

output "cpu_batch_job_definition_arn" {
  value = aws_batch_job_definition.cpu.arn
}

output "cpu_worker_ecr_repository" {
  value = aws_ecr_repository.cpu_worker.repository_url
}

output "ops_sns_topic" {
  value = aws_sns_topic.ops.arn
}
