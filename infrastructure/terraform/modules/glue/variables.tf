variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment (dev)"
  type        = string
}

variable "s3_bucket_name" {
  description = "S3 bucket name for Iceberg data"
  type        = string
}
