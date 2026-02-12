variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "email_endpoint" {
  description = "Email address to receive SNS notifications"
  type        = string
  default     = null
}
