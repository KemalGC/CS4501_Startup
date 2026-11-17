data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  count   = var.vpc_id == null ? 1 : 0
  default = true
}

locals {
  prefix       = "${var.project_name}-${var.environment}"
  vpc_id       = var.vpc_id != null ? var.vpc_id : data.aws_vpc.default[0].id
  storage_name = "${local.prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

data "aws_subnets" "default" {
  count = length(var.public_subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

locals {
  subnet_ids = length(var.public_subnet_ids) > 0 ? var.public_subnet_ids : data.aws_subnets.default[0].ids
}
