# Browser uploads and report downloads use short-lived signatures issued by the API.
# Nothing in this bucket is publicly readable or writable.
resource "aws_s3_bucket" "media" {
  bucket        = local.storage_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD", "POST", "PUT"]
    allowed_origins = var.allowed_origins
    expose_headers  = ["ETag", "x-amz-checksum-sha256", "x-amz-request-id"]
    max_age_seconds = 600
  }
}

# Lifecycle deletion is asynchronous. The application must enforce exact 72-hour
# and 30-day report access deadlines based on jobs.expires_at/owner entitlement.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "delete-temporary-uploads"
    status = "Enabled"

    filter {
      prefix = "uploads/"
    }

    expiration {
      days = var.raw_upload_ttl_days
    }
  }

  rule {
    id     = "delete-free-reports"
    status = "Enabled"

    filter {
      prefix = "reports/free/"
    }

    expiration {
      days = var.free_report_ttl_days
    }
  }

  rule {
    id     = "delete-paid-reports"
    status = "Enabled"

    filter {
      prefix = "reports/paid/"
    }

    expiration {
      days = var.paid_report_ttl_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
