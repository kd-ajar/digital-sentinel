variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for MSK brokers"
  type        = list(string)
}

# CIDR-based access for Kafka ports - avoids circular dependencies
# This is secure because:
# 1. MSK is in private subnets (no direct internet access)
# 2. Only specific ports (9092, 9094) are open
# 3. Client modules (ECS/Lambda/EMR) have explicit egress rules to Kafka ports
variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to access MSK (typically VPC CIDR)"
  type        = list(string)
  default     = []
}

variable "kafka_version" {
  description = "Kafka version"
  type        = string
  default     = "3.5.1"
}

variable "broker_instance_type" {
  description = "Broker instance type"
  type        = string
  default     = "kafka.t3.small"
}

variable "number_of_broker_nodes" {
  description = "Number of broker nodes"
  type        = number
  default     = 3
}

variable "broker_volume_size" {
  description = "Broker EBS volume size in GB"
  type        = number
  default     = 100
}

variable "replication_factor" {
  description = "Default replication factor"
  type        = number
  default     = 3
}

variable "min_insync_replicas" {
  description = "Minimum in-sync replicas"
  type        = number
  default     = 2
}

variable "num_partitions" {
  description = "Default number of partitions"
  type        = number
  default     = 3
}

variable "log_retention_hours" {
  description = "Log retention in hours"
  type        = number
  default     = 168
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}
