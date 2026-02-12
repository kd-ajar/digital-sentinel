# S3 Bucket Module for Lakehouse

resource "aws_s3_bucket" "lakehouse" {
  bucket = "${var.s3_bucket_prefix}-lakehouse-${var.environment}"

  tags = {
    Name        = "${var.s3_bucket_prefix}-lakehouse"
    Environment = var.environment
  }
}

# Enable versioning
resource "aws_s3_bucket_versioning" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Enable encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rules for cost optimization
resource "aws_s3_bucket_lifecycle_configuration" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id

  # Bronze layer: Keep 30 days hot, then archive
  rule {
    id     = "bronze-lifecycle"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }

  # Silver layer: Keep 90 days hot, then archive
  rule {
    id     = "silver-lifecycle"
    status = "Enabled"

    filter {
      prefix = "silver/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 730
    }
  }

  # Gold layer: Keep hot indefinitely
  rule {
    id     = "gold-lifecycle"
    status = "Enabled"

    filter {
      prefix = "gold/"
    }

    transition {
      days          = 180
      storage_class = "STANDARD_IA"
    }
  }

  # Athena results: Clean up after 7 days
  rule {
    id     = "athena-results-cleanup"
    status = "Enabled"

    filter {
      prefix = "athena-results/"
    }

    expiration {
      days = 7
    }
  }
}

# Bucket policy to allow QuickSight access
resource "aws_s3_bucket_policy" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowQuickSightAccess"
        Effect = "Allow"
        Principal = {
          Service = "quicksight.amazonaws.com"
        }
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.lakehouse.arn,
          "${aws_s3_bucket.lakehouse.arn}/*"
        ]
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      },
      {
        Sid    = "AllowQuickSightAthenaResults"
        Effect = "Allow"
        Principal = {
          Service = "quicksight.amazonaws.com"
        }
        Action = [
          "s3:PutObject",
          "s3:AbortMultipartUpload"
        ]
        Resource = [
          "${aws_s3_bucket.lakehouse.arn}/athena-results/*"
        ]
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}
