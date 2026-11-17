# The stable Cognito user-pool `sub` is the user ID, not the mutable email.
# Non-key attributes (trial_used_bytes, trial_reserved_bytes, paid_credits etc.)
# are maintained by the Lambda using atomic conditional/transactional writes.
resource "aws_dynamodb_table" "users" {
  name         = "${local.prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }
}

# Each job_id doubles as a video_id across multipart upload and analysis.
# The GSI permits ownership-bound listing and reconciliation of old reservations.
resource "aws_dynamodb_table" "jobs" {
  name         = "${local.prefix}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "user_id-created_at-index"
    hash_key        = "user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
