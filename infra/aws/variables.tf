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

variable "worker_command" {
  type        = list(string)
  default     = ["python", "-m", "aws_app.worker"]
  description = "Container command to process one Batch job; the job input is passed through AWS Batch environment overrides."
}

variable "enable_gpu" {
  type        = bool
  default     = false
  description = "Safety gate for the unimplemented paid fractional-GPU lane; cannot be enabled in this CPU-only stack."

  validation {
    condition     = var.enable_gpu == false
    error_message = "GPU Deep Analysis is not implemented or benchmarked; keep enable_gpu=false and follow GPU_PLAN.md."
  }
}

variable "cpu_max_vcpus" {
  description = "Fargate Batch maximum concurrent vCPUs. 6 permits up to three 2-vCPU jobs (subject to account service quotas)."
  type        = number
  default     = 6

  validation {
    condition     = var.cpu_max_vcpus >= 2 && var.cpu_max_vcpus <= 32 && floor(var.cpu_max_vcpus) == var.cpu_max_vcpus
    error_message = "cpu_max_vcpus must be an integer between 2 and 32."
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
