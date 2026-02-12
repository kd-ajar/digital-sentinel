# Athena Module Outputs

output "workgroup_name" {
  description = "Athena workgroup name"
  value       = aws_athena_workgroup.analytics.name
}

output "workgroup_arn" {
  description = "Athena workgroup ARN"
  value       = aws_athena_workgroup.analytics.arn
}

output "quicksight_role_arn" {
  description = "IAM role ARN for QuickSight to access Athena"
  value       = aws_iam_role.quicksight_athena.arn
}

output "query_results_location" {
  description = "S3 location for Athena query results"
  value       = "s3://${var.s3_bucket_name}/athena-results/"
}

output "named_queries" {
  description = "Map of named query IDs"
  value = {
    entity_risk_summary   = aws_athena_named_query.entity_risk_summary.id
    user_anomalies        = aws_athena_named_query.user_anomalies.id
    global_activity_trend = aws_athena_named_query.global_activity_trend.id
  }
}
