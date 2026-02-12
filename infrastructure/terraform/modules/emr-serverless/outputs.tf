# EMR Serverless Outputs

# Application IDs
output "bronze_application_id" {
  description = "EMR Serverless Bronze Application ID"
  value       = aws_emrserverless_application.bronze.id
}

output "silver_application_id" {
  description = "EMR Serverless Silver Application ID"
  value       = aws_emrserverless_application.silver.id
}

output "gold_application_id" {
  description = "EMR Serverless Gold Application ID"
  value       = aws_emrserverless_application.gold.id
}

# Application ARNs
output "bronze_application_arn" {
  description = "EMR Serverless Bronze Application ARN"
  value       = aws_emrserverless_application.bronze.arn
}

output "silver_application_arn" {
  description = "EMR Serverless Silver Application ARN"
  value       = aws_emrserverless_application.silver.arn
}

output "gold_application_arn" {
  description = "EMR Serverless Gold Application ARN"
  value       = aws_emrserverless_application.gold.arn
}

# Execution Role
output "execution_role_arn" {
  description = "EMR Serverless Execution Role ARN"
  value       = aws_iam_role.emr_serverless_execution.arn
}

output "execution_role_name" {
  description = "EMR Serverless Execution Role Name"
  value       = aws_iam_role.emr_serverless_execution.name
}

# Security Group
output "security_group_id" {
  description = "EMR Serverless Security Group ID"
  value       = aws_security_group.emr_serverless.id
}

# Log Group Names
output "bronze_log_group" {
  description = "CloudWatch Log Group for Bronze application"
  value       = aws_cloudwatch_log_group.bronze.name
}

output "silver_log_group" {
  description = "CloudWatch Log Group for Silver application"
  value       = aws_cloudwatch_log_group.silver.name
}

output "gold_log_group" {
  description = "CloudWatch Log Group for Gold application"
  value       = aws_cloudwatch_log_group.gold.name
}

# Configuration outputs for scripts
output "applications" {
  description = "Map of application configurations for submission scripts"
  value = {
    bronze = {
      id         = aws_emrserverless_application.bronze.id
      arn        = aws_emrserverless_application.bronze.arn
      name       = aws_emrserverless_application.bronze.name
      type       = "streaming"
      max_cpu    = var.bronze_max_cpu
      max_memory = var.bronze_max_memory
    }
    silver = {
      id         = aws_emrserverless_application.silver.id
      arn        = aws_emrserverless_application.silver.arn
      name       = aws_emrserverless_application.silver.name
      type       = "batch"
      max_cpu    = var.silver_max_cpu
      max_memory = var.silver_max_memory
    }
    gold = {
      id         = aws_emrserverless_application.gold.id
      arn        = aws_emrserverless_application.gold.arn
      name       = aws_emrserverless_application.gold.name
      type       = "batch"
      max_cpu    = var.gold_max_cpu
      max_memory = var.gold_max_memory
    }
  }
}
