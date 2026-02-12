# Data source for AWS account ID
data "aws_caller_identity" "current" {}

# VPC Module
module "vpc" {
  source = "./modules/vpc"

  project_name       = var.project_name
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  aws_region         = var.aws_region
}

# S3 Lakehouse Module
module "s3" {
  source = "./modules/s3"

  project_name     = var.project_name
  environment      = var.environment
  s3_bucket_prefix = var.s3_bucket_prefix
  account_id       = data.aws_caller_identity.current.account_id
}

# IAM Roles Module
module "iam" {
  source = "./modules/iam"

  project_name            = var.project_name
  environment             = var.environment
  s3_bucket_arn           = module.s3.bucket_arn
  ecs_task_definition_arn = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project_name}-ingest:*"
}

# ECS Fargate Module (commented out - using local Docker Kafka for development)
module "ecs" {
  source = "./modules/ecs"

  project_name            = var.project_name
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  vpc_cidr                = var.vpc_cidr  # For Kafka egress rules
  private_subnet_ids      = module.vpc.private_subnet_ids
  execution_role_arn      = module.iam.ecs_execution_role_arn
  task_role_arn           = module.iam.ecs_task_role_arn
  kafka_bootstrap_servers = module.msk.bootstrap_brokers_tls
  aws_region              = var.aws_region
  task_cpu                = var.ecs_task_cpu
  task_memory             = var.ecs_task_memory
  initial_desired_count   = var.ecs_initial_desired_count
}

# MSK Kafka Module
module "msk" {
  source = "./modules/msk"

  project_name       = var.project_name
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  
  # VPC CIDR-based access for Kafka ports
  # This is secure because:
  # 1. MSK is in private subnets (no direct internet access)
  # 2. Only specific ports (9092, 9094) are open
  # 3. Only VPC resources with Kafka egress rules can connect
  # 4. Avoids circular dependencies with ECS/Lambda (they need bootstrap_servers)
  allowed_cidr_blocks = [var.vpc_cidr]
  
  kafka_version          = var.kafka_version
  broker_instance_type   = var.msk_broker_instance_type
  number_of_broker_nodes = var.msk_number_of_broker_nodes
}

# Glue Data Catalog Module
module "glue" {
  source = "./modules/glue"

  project_name   = var.project_name
  environment    = var.environment
  s3_bucket_name = module.s3.bucket_name
}

# SNS Module for Data Quality Alerts
module "sns" {
  source = "./modules/sns"

  project_name   = var.project_name
  environment    = var.environment
  email_endpoint = var.notification_email
}

# ============================================================================
# Secrets Manager Module - Secure storage for credentials
# ============================================================================
module "secrets_manager" {
  source = "./modules/secrets-manager"

  project_name = var.project_name
  environment  = var.environment
}

# ========================================================== ==================
# EMR Serverless Module - Medallion Architecture
# Separate applications for Bronze (streaming), Silver (batch), Gold (batch)
# ============================================================================
module "emr_serverless" {
  source = "./modules/emr-serverless"

  project_name          = var.project_name
  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  vpc_cidr              = var.vpc_cidr  # For Kafka egress rules
  private_subnet_ids    = module.vpc.private_subnet_ids
  # SECURE: MSK now owns its ingress rules referencing EMR SG
  # EMR module exports security_group_id, MSK creates ingress rules for it
  s3_bucket_name        = module.s3.bucket_name
  s3_bucket_arn         = module.s3.bucket_arn
  emr_release_label     = var.emr_serverless_release_label

  # Service Quota - Account-level vCPU limit
  emr_serverless_vcpu_quota = var.emr_serverless_vcpu_quota

  # Bronze (Streaming) Configuration
  bronze_max_cpu                  = var.emr_serverless_bronze_max_cpu
  bronze_max_memory               = var.emr_serverless_bronze_max_memory
  bronze_initial_capacity_enabled = var.emr_serverless_bronze_initial_capacity

  # Silver (Batch) Configuration
  silver_max_cpu    = var.emr_serverless_silver_max_cpu
  silver_max_memory = var.emr_serverless_silver_max_memory

  # Gold (Batch) Configuration
  gold_max_cpu    = var.emr_serverless_gold_max_cpu
  gold_max_memory = var.emr_serverless_gold_max_memory

  # Auto-stop configuration
  idle_timeout_minutes = var.emr_serverless_idle_timeout

  # Alerting configuration
  sns_topic_arn    = module.sns.topic_arn
  slack_secret_arn = module.secrets_manager.slack_bot_token_secret_arn

  depends_on = [module.glue, module.sns, module.secrets_manager]
}

# ============================================================================
# Athena Module - Bridge between Gold Iceberg tables and QuickSight
# ============================================================================
module "athena" {
  source = "./modules/athena"

  project_name   = var.project_name
  environment    = var.environment
  aws_region     = var.aws_region
  account_id     = data.aws_caller_identity.current.account_id
  s3_bucket_name = module.s3.bucket_name
  glue_database  = module.glue.database_name

  depends_on = [module.glue, module.s3]
}
