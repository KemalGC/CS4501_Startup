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
    # Protect lifetime processing allowances and future paid-credit records.
    # AWS bills PITR backup storage separately from table read/write traffic.
    enabled = true
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

  # Sparse partition: only the owner's expressly opted-in videos enter this
  # index. An admin cannot enumerate unconsented users through the admin API.
  attribute {
    name = "admin_partition"
    type = "S"
  }

  global_secondary_index {
    name            = "user_id-created_at-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "user_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "status-expires_at-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "expires_at"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "admin_partition-created_at-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "admin_partition"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  # Terminal records set ttl_epoch transactionally. Pending reservations
  # deliberately have no TTL, so quota cannot leak if a job is orphaned.
  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

# Anonymous website feedback is separate from user/job records, so public
# submission cannot read or enumerate private videos. A private 90-day TTL
# expires submissions; short-lived daily counters prevent unbounded writes.
resource "aws_dynamodb_table" "feedback" {
  name         = "${local.prefix}-feedback"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feedback_id"

  attribute {
    name = "feedback_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }
}

# Every issued administrator video URL is recorded transactionally alongside
# a fresh DynamoDB consent check. 90-day TTL by default, no raw video URLs,
# AWS access tokens or user email addresses are placed in this table.
resource "aws_dynamodb_table" "admin_access_audit" {
  name         = "${local.prefix}-admin-access-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "audit_id"

  attribute {
    name = "audit_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}
