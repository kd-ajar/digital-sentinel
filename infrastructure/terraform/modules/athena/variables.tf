# Athena Module Variables

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
}

variable "s3_bucket_name" {
  description = "S3 bucket name for data and Athena results"
  type        = string
}

variable "glue_database" {
  description = "Glue database name containing Gold tables"
  type        = string
}
