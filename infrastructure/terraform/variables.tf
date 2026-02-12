# Input Variables

# AWS Configuration
variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "wikiguard"
}

# S3 Configuration
variable "s3_bucket_prefix" {
  description = "Prefix for S3 bucket names"
  type        = string
  default     = "wikiguard-lakehouse"
}

# Notification Configuration
variable "notification_email" {
  description = "Email address for pipeline notifications"
  type        = string
}

# VPC Configuration
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# ECS Configuration
variable "ecs_task_cpu" {
  description = "CPU units for ECS task (256 = 0.25 vCPU)"
  type        = string
  default     = "256"
}

variable "ecs_task_memory" {
  description = "Memory for ECS task in MB"
  type        = string
  default     = "512"
}

variable "ecs_initial_desired_count" {
  description = "Initial desired count for ECS service (0 = controlled by EventBridge)"
  type        = number
  default     = 0
}

# MSK Configuration
variable "kafka_version" {
  description = "Kafka version for MSK cluster"
  type        = string
  default     = "3.8.x"
}

variable "msk_broker_instance_type" {
  description = "Instance type for MSK brokers"
  type        = string
  default     = "kafka.t3.small"
}

variable "msk_number_of_broker_nodes" {
  description = "Number of broker nodes (must be multiple of AZs)"
  type        = number
  default     = 3
}

# EMR Configuration
variable "emr_release_label" {
  description = "EMR release version"
  type        = string
  default     = "emr-7.9.0"
}

variable "emr_master_instance_type" {
  description = "EMR master node instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "emr_core_instance_type" {
  description = "EMR core node instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "emr_core_instance_count" {
  description = "Number of EMR core instances"
  type        = number
  default     = 2
}

variable "emr_termination_protection" {
  description = "Enable EMR termination protection"
  type        = bool
  default     = false
}

variable "emr_auto_termination_idle_timeout" {
  description = "EMR auto-termination idle timeout in seconds (3600 = 1 hour, 0 = disabled)"
  type        = number
  default     = 3600
}

variable "emr_step_concurrency_level" {
  description = "Number of EMR steps that can run concurrently. Set to 3 for Bronze, Silver, Gold medallion layers."
  type        = number
  default     = 3
}

# ============================================================================
# EMR Serverless Configuration (Medallion Architecture)
# ============================================================================

variable "emr_serverless_release_label" {
  description = "EMR Serverless release version (emr-7.2.0 = Spark 3.5)"
  type        = string
  default     = "emr-7.2.0"
}

# Bronze Application (Streaming)
variable "emr_serverless_bronze_max_cpu" {
  description = "Max vCPU for Bronze application quota (streaming)"
  type        = string
  default     = "16 vCPU"
}

variable "emr_serverless_bronze_max_memory" {
  description = "Max memory for Bronze application quota"
  type        = string
  default     = "20 GB"
}

variable "emr_serverless_bronze_initial_capacity" {
  description = "Enable pre-initialized capacity for Bronze (keeps workers warm for streaming)"
  type        = bool
  default     = true
}

# Silver Application (Batch)
variable "emr_serverless_silver_max_cpu" {
  description = "Max vCPU for Silver application quota (batch)"
  type        = string
  default     = "32 vCPU"
}

variable "emr_serverless_silver_max_memory" {
  description = "Max memory for Silver application quota"
  type        = string
  default     = "32 GB"
}

# Gold Application (Batch)
variable "emr_serverless_gold_max_cpu" {
  description = "Max vCPU for Gold application quota (batch)"
  type        = string
  default     = "32 vCPU"
}

variable "emr_serverless_gold_max_memory" {
  description = "Max memory for Gold application quota"
  type        = string
  default     = "32 GB"
}

variable "emr_serverless_idle_timeout" {
  description = "Minutes of idle time before auto-stopping applications"
  type        = number
  default     = 15
}

# ============================================================================
# EMR Serverless Account Quota (FREE to increase - only pay for usage)
# ============================================================================
variable "emr_serverless_vcpu_quota" {
  description = "Max concurrent vCPU for EMR Serverless across ALL applications (account-level quota)"
  type        = number
  default     = 32  # Increased from default 16 to handle Bronze + Silver + Gold concurrently
}
