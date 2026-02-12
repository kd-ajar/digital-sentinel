variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "s3_bucket_prefix" {
  description = "Prefix for S3 bucket names (must be globally unique)"
  type        = string
}

variable "account_id" {
  description = "AWS account ID for bucket policy conditions"
  type        = string
  default     = ""
}
