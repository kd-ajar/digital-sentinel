variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "s3_bucket_arn" {
  description = "S3 bucket ARN for permissions"
  type        = string
}

variable "ecs_task_definition_arn" {
  description = "ECS task definition ARN"
  type        = string
}
