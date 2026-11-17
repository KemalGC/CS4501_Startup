terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.98, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "StrokeSense"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Project     = "StrokeSense-AWS-Dev"
    }
  }
}
