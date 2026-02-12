# EMR Serverless Applications for Medallion Architecture
# Separate applications for Bronze (streaming), Silver (batch), and Gold (batch)

# ============================================================================
# Service Quota - Increase EMR Serverless vCPU limit
# Default is 16 vCPU, we need 32 to run Bronze + Silver + Gold concurrently
# NOTE: This is FREE - you only pay for actual usage, not the quota limit
# ============================================================================
resource "aws_servicequotas_service_quota" "emr_serverless_vcpu" {
  quota_code   = "L-D05C8A75"  # Max concurrent vCPU
  service_code = "emr-serverless"
  value        = var.emr_serverless_vcpu_quota
}

# Security group for EMR Serverless to access MSK
resource "aws_security_group" "emr_serverless" {
  name        = "${var.project_name}-emr-serverless-sg"
  description = "Security group for EMR Serverless applications"
  vpc_id      = var.vpc_id

  # Enable automatic rule cleanup before deletion
  revoke_rules_on_delete = true

  tags = {
    Name        = "${var.project_name}-emr-serverless-sg"
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Allow inbound from self (for Spark driver/executor communication)
resource "aws_security_group_rule" "emr_ingress_self" {
  type              = "ingress"
  description       = "Spark driver/executor communication"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.emr_serverless.id
  self              = true
}

# Egress to self (Spark communication)
resource "aws_security_group_rule" "emr_egress_self" {
  type              = "egress"
  description       = "Spark driver/executor communication"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.emr_serverless.id
  self              = true
}

# Egress for AWS services (S3 via Gateway Endpoint, Glue, CloudWatch, etc.)
# Note: S3 traffic goes through VPC Gateway Endpoint (no internet)
# HTTPS is needed for AWS API calls (Glue Data Catalog, CloudWatch, etc.)
resource "aws_security_group_rule" "emr_egress_https" {
  type              = "egress"
  description       = "HTTPS for AWS services (Glue, CloudWatch)"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.emr_serverless.id
  cidr_blocks       = ["0.0.0.0/0"]  # AWS services via NAT/endpoints
}

# Egress to Kafka (MSK) - using VPC CIDR for specific ports
# This is more secure than 0.0.0.0/0 while avoiding circular SG references
resource "aws_security_group_rule" "emr_egress_kafka_plaintext" {
  type              = "egress"
  description       = "Kafka plaintext to MSK"
  from_port         = 9092
  to_port           = 9092
  protocol          = "tcp"
  security_group_id = aws_security_group.emr_serverless.id
  cidr_blocks       = [var.vpc_cidr]
}

resource "aws_security_group_rule" "emr_egress_kafka_tls" {
  type              = "egress"
  description       = "Kafka TLS to MSK"
  from_port         = 9094
  to_port           = 9094
  protocol          = "tcp"
  security_group_id = aws_security_group.emr_serverless.id
  cidr_blocks       = [var.vpc_cidr]
}

# NOTE: MSK now owns its ingress rules referencing this EMR SG
# MSK depends_on EMR module (not the other way around)
# MSK SG now uses CIDR-based rules (var.vpc_cidr) which allows EMR access
# without creating cross-SG references

# IAM Role for EMR Serverless Job Execution
resource "aws_iam_role" "emr_serverless_execution" {
  name = "${var.project_name}-emr-serverless-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "emr-serverless.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-emr-serverless-execution-role"
    Environment = var.environment
  }
}

# Policy for EMR Serverless - S3, Glue, MSK, CloudWatch
resource "aws_iam_role_policy" "emr_serverless_policy" {
  name = "${var.project_name}-emr-serverless-policy"
  role = aws_iam_role.emr_serverless_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          var.s3_bucket_arn,
          "${var.s3_bucket_arn}/*"
        ]
      },
      {
        Sid    = "GlueAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:BatchCreatePartition",
          "glue:BatchDeletePartition",
          "glue:BatchUpdatePartition",
          "glue:CreateDatabase",
          "glue:DeleteDatabase"
        ]
        Resource = "*"
      },
      {
        Sid    = "MSKAccess"
        Effect = "Allow"
        Action = [
          "kafka:DescribeCluster",
          "kafka:DescribeClusterV2",
          "kafka:GetBootstrapBrokers",
          "kafka-cluster:Connect",
          "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
          "kafka-cluster:DescribeTopic",
          "kafka-cluster:ReadData",
          "kafka-cluster:WriteData",
          "kafka-cluster:DescribeClusterDynamicConfiguration"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = [
          "arn:aws:logs:*:*:log-group:/aws/emr-serverless/*",
          "arn:aws:logs:*:*:log-group:/aws/emr-serverless/*:*"
        ]
      },
      {
        Sid    = "EC2NetworkAccess"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      },
      {
        Sid    = "SecretsManagerAccess"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.slack_secret_arn
        ]
      },
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = var.sns_topic_arn
      }
    ]
  })
}

# ============================================================================
# BRONZE APPLICATION - Streaming (Kafka → Iceberg Bronze)
# Characteristics: Always running, low latency, stateful, must be stable
# ============================================================================
resource "aws_emrserverless_application" "bronze" {
  name          = "${var.project_name}-bronze-${var.environment}"
  release_label = var.emr_release_label
  type          = "SPARK"

  # Application quota limits
  maximum_capacity {
    cpu    = var.bronze_max_cpu
    memory = var.bronze_max_memory
  }

  # Pre-initialized capacity for streaming (keeps workers warm)
  dynamic "initial_capacity" {
    for_each = var.bronze_initial_capacity_enabled ? [1] : []
    content {
      initial_capacity_type = "Driver"
      initial_capacity_config {
        worker_count = var.bronze_initial_driver_count
        worker_configuration {
          cpu    = "2 vCPU"
          memory = "4 GB"
        }
      }
    }
  }

  dynamic "initial_capacity" {
    for_each = var.bronze_initial_capacity_enabled ? [1] : []
    content {
      initial_capacity_type = "Executor"
      initial_capacity_config {
        worker_count = var.bronze_initial_executor_count
        worker_configuration {
          cpu    = "2 vCPU"
          memory = "4 GB"
        }
      }
    }
  }

  # Auto-stop configuration
  auto_stop_configuration {
    enabled             = true
    idle_timeout_minutes = var.idle_timeout_minutes
  }

  # Auto-start configuration
  auto_start_configuration {
    enabled = true
  }

  # Network configuration for MSK access
  network_configuration {
    security_group_ids = [aws_security_group.emr_serverless.id]
    subnet_ids         = var.private_subnet_ids
  }

  tags = {
    Name        = "${var.project_name}-bronze-${var.environment}"
    Environment = var.environment
    Layer       = "bronze"
    Type        = "streaming"
  }
}

# ============================================================================
# SILVER APPLICATION - Batch (Bronze → Silver, every 15 min)
# Characteristics: Triggered, moderate CPU, dedup/clean/enrich
# ============================================================================
resource "aws_emrserverless_application" "silver" {
  name          = "${var.project_name}-silver-${var.environment}"
  release_label = var.emr_release_label
  type          = "SPARK"

  # Application quota limits
  maximum_capacity {
    cpu    = var.silver_max_cpu
    memory = var.silver_max_memory
  }

  # Optional initial capacity for Silver
  dynamic "initial_capacity" {
    for_each = var.silver_initial_capacity_enabled ? [1] : []
    content {
      initial_capacity_type = "Driver"
      initial_capacity_config {
        worker_count = 1
        worker_configuration {
          cpu    = "2 vCPU"
          memory = "4 GB"
        }
      }
    }
  }

  # Auto-stop configuration
  auto_stop_configuration {
    enabled             = true
    idle_timeout_minutes = var.idle_timeout_minutes
  }

  # Auto-start configuration
  auto_start_configuration {
    enabled = true
  }

  # Network configuration for S3/Glue access
  network_configuration {
    security_group_ids = [aws_security_group.emr_serverless.id]
    subnet_ids         = var.private_subnet_ids
  }

  tags = {
    Name        = "${var.project_name}-silver-${var.environment}"
    Environment = var.environment
    Layer       = "silver"
    Type        = "batch"
  }
}

# ============================================================================
# GOLD APPLICATION - Batch (Silver → Gold, every 15 min)
# Characteristics: Aggregations, windowing, small data
# ============================================================================
resource "aws_emrserverless_application" "gold" {
  name          = "${var.project_name}-gold-${var.environment}"
  release_label = var.emr_release_label
  type          = "SPARK"

  # Application quota limits
  maximum_capacity {
    cpu    = var.gold_max_cpu
    memory = var.gold_max_memory
  }

  # Optional initial capacity for Gold
  dynamic "initial_capacity" {
    for_each = var.gold_initial_capacity_enabled ? [1] : []
    content {
      initial_capacity_type = "Driver"
      initial_capacity_config {
        worker_count = 1
        worker_configuration {
          cpu    = "2 vCPU"
          memory = "4 GB"
        }
      }
    }
  }

  # Auto-stop configuration
  auto_stop_configuration {
    enabled             = true
    idle_timeout_minutes = var.idle_timeout_minutes
  }

  # Auto-start configuration
  auto_start_configuration {
    enabled = true
  }

  # Network configuration
  network_configuration {
    security_group_ids = [aws_security_group.emr_serverless.id]
    subnet_ids         = var.private_subnet_ids
  }

  tags = {
    Name        = "${var.project_name}-gold-${var.environment}"
    Environment = var.environment
    Layer       = "gold"
    Type        = "batch"
  }
}

# CloudWatch Log Groups for each application
resource "aws_cloudwatch_log_group" "bronze" {
  name              = "/aws/emr-serverless/${var.project_name}-bronze-${var.environment}"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-bronze-logs"
    Environment = var.environment
    Layer       = "bronze"
  }
}

resource "aws_cloudwatch_log_group" "silver" {
  name              = "/aws/emr-serverless/${var.project_name}-silver-${var.environment}"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-silver-logs"
    Environment = var.environment
    Layer       = "silver"
  }
}

resource "aws_cloudwatch_log_group" "gold" {
  name              = "/aws/emr-serverless/${var.project_name}-gold-${var.environment}"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-gold-logs"
    Environment = var.environment
    Layer       = "gold"
  }
}
