# Athena Workgroup for Gold Layer Analytics
# Used as bridge between Iceberg tables and QuickSight

resource "aws_athena_workgroup" "analytics" {
  name        = "${var.project_name}-${var.environment}-analytics"
  description = "Workgroup for ${var.project_name} Gold layer analytics and QuickSight"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${var.s3_bucket_name}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-analytics"
    Environment = var.environment
    Purpose     = "QuickSight-Gold-Integration"
  }
}

# S3 location for Athena query results
resource "aws_s3_object" "athena_results_folder" {
  bucket = var.s3_bucket_name
  key    = "athena-results/"
  content_type = "application/x-directory"
}

# IAM Role for QuickSight to access Athena and S3
resource "aws_iam_role" "quicksight_athena" {
  name = "${var.project_name}-${var.environment}-quicksight-athena-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "quicksight.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-quicksight-athena-role"
    Environment = var.environment
  }
}

# Policy for QuickSight to query Athena
resource "aws_iam_role_policy" "quicksight_athena" {
  name = "${var.project_name}-${var.environment}-quicksight-athena-policy"
  role = aws_iam_role.quicksight_athena.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AthenaAccess"
        Effect = "Allow"
        Action = [
          "athena:BatchGetQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetQueryResultsStream",
          "athena:ListQueryExecutions",
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup",
          "athena:GetDataCatalog",
          "athena:GetDatabase",
          "athena:GetTableMetadata",
          "athena:ListDataCatalogs",
          "athena:ListDatabases",
          "athena:ListTableMetadata"
        ]
        Resource = [
          aws_athena_workgroup.analytics.arn,
          "arn:aws:athena:${var.aws_region}:${var.account_id}:datacatalog/AwsDataCatalog"
        ]
      },
      {
        Sid    = "GlueAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:BatchGetPartition"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${var.glue_database}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${var.glue_database}/*"
        ]
      },
      {
        Sid    = "S3ReadAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/data/gold_*/*"
        ]
      },
      {
        Sid    = "S3WriteResultsAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:AbortMultipartUpload"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}/athena-results/*"
        ]
      }
    ]
  })
}

# Named queries for common Gold layer analytics (optional but helpful)
resource "aws_athena_named_query" "entity_risk_summary" {
  name        = "entity-risk-summary"
  description = "Top entities by risk score in last 24 hours"
  workgroup   = aws_athena_workgroup.analytics.name
  database    = var.glue_database

  query = <<-EOT
    SELECT 
      entity,
      wiki,
      window_start,
      total_events,
      edit_count,
      revert_count,
      anonymous_edit_count,
      risk_score,
      revert_ratio,
      anonymous_ratio
    FROM gold_entity_metrics_10min
    WHERE event_date >= current_date - interval '1' day
      AND risk_score > 0
    ORDER BY risk_score DESC, total_events DESC
    LIMIT 100
  EOT
}

resource "aws_athena_named_query" "user_anomalies" {
  name        = "user-anomalies"
  description = "Users with suspicious activity patterns"
  workgroup   = aws_athena_workgroup.analytics.name
  database    = var.glue_database

  query = <<-EOT
    SELECT 
      user_name,
      window_start,
      total_events,
      edit_count,
      revert_count,
      entities_edited,
      wikis_touched,
      user_risk_score,
      is_new_user_blitz,
      is_mass_reverter,
      is_cross_wiki_active
    FROM gold_user_metrics_10min
    WHERE event_date >= current_date - interval '1' day
      AND user_risk_score > 0
    ORDER BY user_risk_score DESC
    LIMIT 100
  EOT
}

resource "aws_athena_named_query" "global_activity_trend" {
  name        = "global-activity-trend"
  description = "Global Wikipedia activity over time"
  workgroup   = aws_athena_workgroup.analytics.name
  database    = var.glue_database

  query = <<-EOT
    SELECT 
      window_start,
      total_events,
      total_edits,
      total_reverts,
      total_anonymous,
      unique_users,
      unique_entities,
      revert_ratio,
      anonymous_ratio,
      avg_processing_lag
    FROM gold_global_metrics_10min
    WHERE event_date >= current_date - interval '1' day
    ORDER BY window_start DESC
  EOT
}
