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

  # Sparse, time-bounded reconciliation queries avoid scanning every user's
  # historical reports on each scheduled cleanup pass.
  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "expires_at"
    type = "N"
  }

  global_secondary_index {
    name            = "user_id-created_at-index"
    hash_key        = "user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "status-expires_at-index"
    hash_key        = "status"
    range_key       = "expires_at"
    projection_type = "ALL"
  }

  # Terminal records set ttl_epoch transactionally. Pending reservations
  # deliberately have no TTL, so quota cannot leak if a job is orphaned.
  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
