variable "aws_region" {
  description = "AWS region for this isolated development stack; keep compute and S3 in one region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Isolated environment suffix, separate from the existing Render/production website."
  type        = string
  default     = "aws-dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}$", var.environment))
    error_message = "Use a short lowercase environment name (letters, digits, hyphens)."
  }
}

variable "project_name" {
  type        = string
  description = "Short lowercase resource prefix."
  default     = "strokesense"
}

variable "vpc_id" {
  type        = string
  default     = null
  description = "Existing VPC ID; null means use the account default VPC. Never create a NAT gateway for this stack."
}

variable "public_subnet_ids" {
  type        = list(string)
  default     = []
  description = "Existing public subnet IDs with an Internet Gateway route. Empty uses subnets in the default VPC."
}

variable "allowed_origins" {
  type = list(string)
  default = [
    "https://strokesense-aws-dev.vercel.app",
    "http://localhost:8000",
    "http://localhost:3000",
    "http://localhost:5173",
  ]
  description = "Exact Vercel development and local origins permitted to call the API; never use * for authenticated operations."
}

variable "cognito_callback_urls" {
  type = list(string)
  default = [
    "https://strokesense-aws-dev.vercel.app/demos/",
    "http://localhost:8000/demos/",
    "http://localhost:3000/demos/",
    "http://localhost:5173/demos/",
  ]
  description = "Exact SPA OAuth redirect destinations; adjust to the real frontend callback route before apply."
}

variable "cognito_logout_urls" {
  type = list(string)
  default = [
    "https://strokesense-aws-dev.vercel.app/",
    "http://localhost:8000/",
    "http://localhost:3000/",
    "http://localhost:5173/",
  ]
  description = "Exact SPA OAuth logout destinations."
}

variable "cognito_domain_prefix" {
  type        = string
  default     = "strokesense-dev"
  description = "Cognito hosted-UI domain prefix; the AWS account ID is appended. Cognito reserves aws, amazon and cognito, so none may appear here."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$", var.cognito_domain_prefix)) && !can(regex("aws|amazon|cognito", var.cognito_domain_prefix))
    error_message = "cognito_domain_prefix must be lowercase letters, digits and hyphens, and must not contain aws, amazon or cognito."
  }
}

variable "api_reserved_concurrency" {
  type        = number
  default     = -1
  description = "Reserved concurrency for the API Lambda; -1 means unreserved. AWS keeps 10 executions unreserved, so a 10-execution account quota allows no reservation. Restore 10 after the account quota is raised."

  validation {
    condition     = var.api_reserved_concurrency >= -1 && floor(var.api_reserved_concurrency) == var.api_reserved_concurrency
    error_message = "api_reserved_concurrency must be -1 (unreserved) or a non-negative integer."
  }
}

variable "reconcile_reserved_concurrency" {
  type        = number
  default     = -1
  description = "Reserved concurrency for the reconciliation Lambda; -1 means unreserved. Restore 1 (no overlapping runs) after the account quota is raised."

  validation {
    condition     = var.reconcile_reserved_concurrency >= -1 && floor(var.reconcile_reserved_concurrency) == var.reconcile_reserved_concurrency
    error_message = "reconcile_reserved_concurrency must be -1 (unreserved) or a non-negative integer."
  }
}

variable "google_oauth_client_id" {
  description = "Google OAuth Web Client ID for Cognito social sign-in. Obtain only after recording the planned Cognito domain."
  type        = string
  sensitive   = true
}

variable "google_oauth_client_secret" {
  description = "Google OAuth Web Client Secret. Pass through a protected environment/variable store; Terraform state also contains it."
  type        = string
  sensitive   = true
}

variable "api_lambda_zip_path" {
  description = "Path to a locally built deployment ZIP containing the top-level aws_app Python package. No Lambda is created until terraform apply."
  type        = string
  default     = "dist/strokesense-api-lambda.zip"
}

variable "api_lambda_handler" {
  type        = string
  default     = "aws_app.handler.lambda_handler"
  description = "Python module/function in api_lambda_zip_path."
}

variable "worker_image_tag" {
  type        = string
  default     = "cpu-latest"
  description = "ECR image tag supplied by the existing CPU analysis worker build."
}

variable "enable_cpu_analysis" {
  type        = bool
  default     = false
  description = "Enable user-facing CPU submissions through the API and its Batch queue. Preserve the deployed value during the isolated GPU smoke test."
}

variable "enable_cpu_smoke_queue" {
  type        = bool
  default     = false
  description = "Enable only the Batch queue for a manual operator-submitted test, without authorizing public API submissions. Set cpu_max_vcpus=2 and use a benchmarked worker_image_tag."
}

variable "worker_command" {
  type        = list(string)
  default     = ["python", "-m", "aws_app.worker"]
  description = "Container command to process one Batch job; the job input is passed through AWS Batch environment overrides."
}


variable "enable_paid_gpu_queue_scaffold" {
  type        = bool
  default     = false
  description = "Explicit opt-in to create inert paid-GPU SQS FIFO/DLQ and disabled dispatcher Lambda plumbing. Never launches GPU compute or enables SQS consumption."
}

variable "enable_gpu" {
  type        = bool
  default     = false
  description = "Review-only GPU EC2 smoke infrastructure; requires separate smoke flags and explicit local acknowledgement. Never enables paid or production GPU."

  validation {
    condition = !var.enable_gpu || (
      var.gpu_smoke_mode &&
      var.gpu_smoke_approval == "I_APPROVE_ONE_G6F_SMOKE_INSTANCE" &&
      !var.enable_paid_gpu_queue_scaffold &&
      !var.enable_cpu_smoke_queue &&
      var.enable_gpu_image_repository
    )
    # enable_cpu_analysis is deliberately NOT required to be false: the smoke
    # stack (own ECS cluster, ASG, SGs, roles, log group) is isolated from the
    # live CPU Batch analyzer, and forcing it off would disable production CPU.
    error_message = "To provision only the isolated GPU smoke infrastructure, set gpu_smoke_mode=true, enable_gpu_image_repository=true, gpu_smoke_approval=I_APPROVE_ONE_G6F_SMOKE_INSTANCE; the paid GPU queue and CPU smoke queue must remain off."
  }
}

variable "cpu_max_vcpus" {
  description = "Fargate Batch maximum concurrent vCPUs. 10 permits up to five 2-vCPU jobs (subject to account Fargate quotas)."
  type        = number
  default     = 10

  validation {
    condition     = var.cpu_max_vcpus >= 2 && var.cpu_max_vcpus <= 32 && floor(var.cpu_max_vcpus) == var.cpu_max_vcpus
    error_message = "cpu_max_vcpus must be an integer between 2 and 32."
  }
}

variable "cpu_global_daily_limit" {
  description = "Hard global cap on CPU Batch submissions per UTC day. Applied atomically in DynamoDB; not a dollar cap."
  type        = number
  default     = 5

  validation {
    condition     = var.cpu_global_daily_limit >= 1 && var.cpu_global_daily_limit <= 100 && floor(var.cpu_global_daily_limit) == var.cpu_global_daily_limit
    error_message = "cpu_global_daily_limit must be an integer from 1 to 100."
  }
}

variable "cpu_global_monthly_limit" {
  description = "Hard global cap on CPU Batch submissions per UTC calendar month. Applied atomically in DynamoDB."
  type        = number
  default     = 50

  validation {
    condition     = var.cpu_global_monthly_limit >= 1 && var.cpu_global_monthly_limit <= 1000 && floor(var.cpu_global_monthly_limit) == var.cpu_global_monthly_limit
    error_message = "cpu_global_monthly_limit must be an integer from 1 to 1000."
  }
}

variable "cpu_job_timeout_seconds" {
  type        = number
  default     = 3600
  description = "Cost safety net for a stuck analysis; revise after benchmarking representative 100 MB free and 750 MB paid clips."
}

variable "free_lifetime_bytes" {
  type        = number
  default     = 300000000
  description = "Lifetime successfully processed video quota for free users (300 decimal MB)."
}

variable "free_max_video_bytes" {
  type        = number
  default     = 100000000
  description = "Maximum single free upload (100 decimal MB), preserving the current limit."
}

variable "paid_max_video_bytes" {
  type        = number
  default     = 750000000
  description = "Maximum single paid upload (750 decimal MB). GPU Deep Analysis is NOT enabled by this Terraform stack."
}

variable "free_report_ttl_days" {
  type        = number
  default     = 3
  description = "S3 eventual cleanup days for free reports. Lambda enforces exact expiry before lifecycle deletion."
}

variable "paid_report_ttl_days" {
  type        = number
  default     = 30
  description = "S3 eventual cleanup days for paid reports. Lambda enforces exact expiry before lifecycle deletion."
}

variable "raw_upload_ttl_days" {
  type        = number
  default     = 7
  description = "S3 cleanup period for uploaded raw videos."
}

variable "terminal_job_record_grace_days" {
  type        = number
  default     = 7
  description = "Days after report expiry (or terminal failure) before owner-only My Analyses metadata expires; default preserves current behavior. Increase only with new privacy consent."

  validation {
    condition     = var.terminal_job_record_grace_days >= 1 && var.terminal_job_record_grace_days <= 30 && floor(var.terminal_job_record_grace_days) == var.terminal_job_record_grace_days
    error_message = "Choose an integer from 1 to 30 days and obtain approval before extending retention."
  }
}

variable "admin_cognito_subs" {
  type        = list(string)
  default     = []
  description = "Cognito user sub IDs allowed to review opted-in videos, additionally requiring strokesense-admin group membership. Empty denies every admin request; never use email."
  sensitive   = true

  validation {
    condition     = length(var.admin_cognito_subs) <= 5 && alltrue([for value in var.admin_cognito_subs : can(regex("^[A-Za-z0-9_-]{1,128}$", value))])
    error_message = "Allowlist up to five stable Cognito sub identifiers, not email addresses."
  }
}

variable "admin_audit_retention_days" {
  type        = number
  default     = 90
  description = "Security audit retention for admin video-link issuance; no raw URLs or emails are recorded."

  validation {
    condition     = var.admin_audit_retention_days >= 30 && var.admin_audit_retention_days <= 365 && floor(var.admin_audit_retention_days) == var.admin_audit_retention_days
    error_message = "Admin audit retention must be 30–365 whole days."
  }
}

variable "alert_email" {
  type        = string
  nullable    = false
  description = "Required billing/operational alert recipient. Set TF_VAR_alert_email privately before any Terraform plan/apply; SNS email subscription requires confirmation."

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_email))
    error_message = "alert_email must be a valid recipient email address; configure notifications before deployment."
  }
}

variable "monthly_budget_usd" {
  type        = number
  default     = 30
  description = "Account-wide monthly gross-cost alert level in USD; not a hard cap or remaining promotional credit balance."

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "daily_budget_usd" {
  type        = number
  default     = 3
  description = "Account-wide DAILY gross-cost budget in USD. Actual-cost alerts at 25%, 50%, 80%, and 100%; not a hard cap."

  validation {
    condition     = var.daily_budget_usd > 0
    error_message = "daily_budget_usd must be positive."
  }
}

# Explicitly reviewed hardware network/image inputs. These remain inert while
# enable_gpu=false; the guard above permits only the isolated GPU smoke mode.
variable "gpu_subnet_id" {
  type        = string
  default     = ""
  description = "One approved existing public subnet for the GPU EC2 host. Blank by default."
  validation {
    condition     = var.gpu_subnet_id == "" || can(regex("^subnet-[0-9a-f]{8,17}$", var.gpu_subnet_id))
    error_message = "Use an AWS subnet ID; do not enable GPU without confirming its routing."
  }
}

variable "gpu_s3_route_table_ids" {
  type        = list(string)
  default     = []
  description = "Reviewed S3 Gateway VPC Endpoint route tables for a future real-data GPU task subnet. Leave empty for the blank-input GPU smoke; it never changes shared S3 routing."
  validation {
    condition     = length(var.gpu_s3_route_table_ids) <= 5 && alltrue([for id in var.gpu_s3_route_table_ids : can(regex("^rtb-[0-9a-f]{8,17}$", id))])
    error_message = "Provide at most five valid route table IDs."
  }
}

variable "gpu_worker_image_uri" {
  type        = string
  default     = ""
  description = "ECR CUDA image URI pinned to an audited sha256 digest, never a mutable tag."
  validation {
    condition     = var.gpu_worker_image_uri == "" || can(regex("@sha256:[a-f0-9]{64}$", var.gpu_worker_image_uri))
    error_message = "GPU worker image must use an immutable sha256 digest."
  }
}

# Dual-gated, manually scaled, ONE-INSTANCE GPU smoke test; not production.
variable "gpu_smoke_mode" {
  type        = bool
  default     = false
  description = "When true, disable ECS managed scaling and use operator-controlled 0..1 ASG only."
}
variable "gpu_smoke_approval" {
  type        = string
  default     = ""
  description = "Exact local acknowledgement for ONE GPU test environment. Never paste credentials in this variable."
}
variable "enable_gpu_image_repository" {
  type        = bool
  default     = false
  description = "Create private GPU ECR repository independently, before uploading and digest-pinning an image. Does not create GPU compute."
}
