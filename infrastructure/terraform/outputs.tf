# Output Values

output "environment" {
  description = "Current environment"
  value       = var.environment
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

# MSK Outputs
output "msk_cluster_arn" {
  description = "MSK cluster ARN"
  value       = module.msk.cluster_arn
}

output "msk_bootstrap_brokers_tls" {
  description = "MSK bootstrap brokers TLS"
  value       = module.msk.bootstrap_brokers_tls
}

# ECS Outputs
output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = module.ecs.service_name
}

output "ecs_task_definition_arn" {
  description = "ECS task definition ARN"
  value       = module.ecs.task_definition_arn
}

# SNS Outputs
output "sns_topic_arn" {
  description = "SNS topic ARN for data quality alerts"
  value       = module.sns.topic_arn
}

output "sns_topic_name" {
  description = "SNS topic name for data quality alerts"
  value       = module.sns.topic_name
}

# S3 Outputs
output "s3_lakehouse_bucket" {
  description = "S3 lakehouse bucket name"
  value       = module.s3.bucket_name
}

# Glue Outputs
output "glue_database_name" {
  description = "Glue database name"
  value       = module.glue.database_name
}

output "glue_bronze_table_name" {
  description = "Glue bronze table name"
  value       = module.glue.bronze_table_name
}


# ============================================================================
# EMR Serverless Outputs (Medallion Architecture)
# ============================================================================
output "emr_serverless_bronze_app_id" {
  description = "EMR Serverless Bronze Application ID"
  value       = module.emr_serverless.bronze_application_id
}

output "emr_serverless_silver_app_id" {
  description = "EMR Serverless Silver Application ID"
  value       = module.emr_serverless.silver_application_id
}

output "emr_serverless_gold_app_id" {
  description = "EMR Serverless Gold Application ID"
  value       = module.emr_serverless.gold_application_id
}

output "emr_serverless_execution_role_arn" {
  description = "EMR Serverless Execution Role ARN"
  value       = module.emr_serverless.execution_role_arn
}

output "slack_bot_token_secret_name" {
  description = "Secrets Manager secret name for Slack Bot Token"
  value       = module.secrets_manager.slack_bot_token_secret_name
}

# ============================================================================
# Athena Outputs (QuickSight Integration)
# ============================================================================
output "athena_workgroup_name" {
  description = "Athena workgroup name for QuickSight"
  value       = module.athena.workgroup_name
}

output "athena_quicksight_role_arn" {
  description = "IAM role ARN for QuickSight to access Athena"
  value       = module.athena.quicksight_role_arn
}

output "athena_query_results_location" {
  description = "S3 location for Athena query results"
  value       = module.athena.query_results_location
}
