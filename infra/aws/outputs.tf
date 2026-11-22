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

output "dynamodb_admin_access_audit_table" {
  value       = aws_dynamodb_table.admin_access_audit.name
  description = "Restricted DynamoDB table auditing consent-checked admin video URL issuance."
}

output "cognito_admin_group_name" {
  value = aws_cognito_user_group.strokesense_admin.name
}

output "dynamodb_feedback_table" {
  value       = aws_dynamodb_table.feedback.name
  description = "Private table storing anonymous website usability ratings and optional comments."
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

output "gpu_worker_ecr_repository" {
  value       = try(aws_ecr_repository.gpu_worker[0].repository_url, null)
  description = "Private GPU CUDA ECR repository (optional bootstrap, never launches EC2)."
}
output "gpu_smoke_ecs_cluster" {
  value       = try(aws_ecs_cluster.gpu[0].arn, null)
  description = "Review-only ECS-on-EC2 GPU smoke cluster; null while disabled."
}
output "gpu_smoke_asg_name" {
  value       = try(aws_autoscaling_group.gpu[0].name, null)
  description = "Smoke ASG idle at min/max/desired=0; operator explicitly raises its maximum to one for a single host."
}
output "gpu_smoke_ami_id" {
  value       = try(data.aws_ami.gpu_ecs[0].id, null)
  description = "Reviewed official AL2023 ECS GPU AMI with GRID support for the G6f host."
}
output "gpu_smoke_ami_name" {
  value       = try(data.aws_ami.gpu_ecs[0].name, null)
  description = "Official GPU AMI release name, retained for the smoke evidence."
}
output "gpu_smoke_launch_template_id" {
  value       = try(aws_launch_template.gpu[0].id, null)
  description = "Launch template whose numeric version the operator verifies before scaling."
}
output "gpu_smoke_launch_template_version" {
  value       = try(tostring(aws_launch_template.gpu[0].latest_version), null)
  description = "Reviewed numeric launch-template version; never the mutable $Latest alias."
}
output "gpu_smoke_task_definition" {
  value       = try(aws_ecs_task_definition.gpu_preflight[0].arn, null)
  description = "No-customer-media CUDA preflight; requires a manually started EC2 host."
}
output "gpu_smoke_capacity_provider" {
  value       = try(aws_ecs_capacity_provider.gpu[0].name, null)
  description = "Manual-scaling capacity provider for one-instance preflight."
}
output "gpu_smoke_task_security_group" {
  value = try(aws_security_group.gpu_task[0].id, null)
}

output "gpu_smoke_log_group" {
  value       = try(aws_cloudwatch_log_group.gpu_worker[0].name, null)
  description = "Private CloudWatch log group holding the preflight evidence line."
}

output "gpu_smoke_subnet_id" {
  value       = var.enable_gpu && var.gpu_smoke_mode ? var.gpu_subnet_id : null
  description = "Reviewed one-instance GPU host/task subnet for operator-only smoke."
}
