terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # DynamoDB GSI key_schema arrived in 6.29. Require 6.37+ to avoid
      # known index drift/recreation defects in the first releases.
      version = ">= 6.37, < 7.0"
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
