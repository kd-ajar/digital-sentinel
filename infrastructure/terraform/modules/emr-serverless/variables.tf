# EMR Serverless Variables

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
}

# ============================================================================
# Service Quota - Account-level vCPU limit for EMR Serverless
# This is FREE to increase - you only pay for actual usage
# ============================================================================
variable "emr_serverless_vcpu_quota" {
  description = "Max concurrent vCPU for EMR Serverless (account-level quota, FREE to increase)"
  type        = number
  default     = 32  # Enough for Bronze (4) + Silver (4) + Gold (4) + headroom
}

variable "emr_release_label" {
  description = "EMR release version for Serverless"
  type        = string
  default     = "emr-7.2.0"
}

variable "vpc_id" {
  description = "VPC ID for network configuration"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block for Kafka egress rules"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for EMR Serverless"
  type        = list(string)
}

# SECURE ARCHITECTURE: MSK owns its ingress rules referencing EMR SG
# EMR only needs egress to Kafka ports - using VPC CIDR (least-privilege for Kafka)
# This prevents circular dependency: MSK depends_on EMR (not the other way around)

variable "s3_bucket_name" {
  description = "S3 bucket name for data and logs"
  type        = string
}

variable "s3_bucket_arn" {
  description = "S3 bucket ARN"
  type        = string
}

# Bronze Application Configuration (Streaming)
variable "bronze_initial_capacity_enabled" {
  description = "Enable initial capacity for Bronze (keeps workers warm)"
  type        = bool
  default     = true
}

variable "bronze_initial_driver_count" {
  description = "Number of pre-initialized drivers for Bronze"
  type        = number
  default     = 1
}

variable "bronze_initial_executor_count" {
  description = "Number of pre-initialized executors for Bronze"
  type        = number
  default     = 2
}

variable "bronze_max_cpu" {
  description = "Max vCPU for Bronze application quota"
  type        = string
  default     = "16 vCPU"
}

variable "bronze_max_memory" {
  description = "Max memory for Bronze application quota"
  type        = string
  default     = "32 GB"
}

variable "bronze_max_concurrent_runs" {
  description = "Max concurrent job runs for Bronze"
  type        = number
  default     = 1
}

# Silver Application Configuration (Batch - every 15 min)
variable "silver_initial_capacity_enabled" {
  description = "Enable initial capacity for Silver"
  type        = bool
  default     = false
}

variable "silver_max_cpu" {
  description = "Max vCPU for Silver application quota"
  type        = string
  default     = "32 vCPU"
}

variable "silver_max_memory" {
  description = "Max memory for Silver application quota"
  type        = string
  default     = "32 GB"
}

variable "silver_max_concurrent_runs" {
  description = "Max concurrent job runs for Silver"
  type        = number
  default     = 2
}

# Gold Application Configuration (Batch - every 15 min)
variable "gold_initial_capacity_enabled" {
  description = "Enable initial capacity for Gold"
  type        = bool
  default     = false
}

variable "gold_max_cpu" {
  description = "Max vCPU for Gold application quota"
  type        = string
  default     = "32 vCPU"
}

variable "gold_max_memory" {
  description = "Max memory for Gold application quota"
  type        = string
  default     = "32 GB"
}

variable "gold_max_concurrent_runs" {
  description = "Max concurrent job runs for Gold"
  type        = number
  default     = 2
}

# Auto-stop configuration
variable "idle_timeout_minutes" {
  description = "Minutes of idle time before auto-stopping the application"
  type        = number
  default     = 15
}

# SNS Topic ARN for alerts
variable "sns_topic_arn" {
  description = "SNS Topic ARN for data quality alerts"
  type        = string
  default     = ""
}

# Secrets Manager ARN for Slack token
variable "slack_secret_arn" {
  description = "ARN of the Slack Bot Token secret in Secrets Manager"
  type        = string
}
