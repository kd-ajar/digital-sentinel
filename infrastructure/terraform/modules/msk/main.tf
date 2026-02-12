# MSK Kafka Cluster Module

resource "aws_msk_cluster" "main" {
  cluster_name           = "${var.project_name}-kafka"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.number_of_broker_nodes

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.private_subnet_ids
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info {
        volume_size = var.broker_volume_size
      }
    }
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }

  tags = {
    Name        = "${var.project_name}-kafka"
    Environment = var.environment
  }
}

# MSK Configuration
resource "aws_msk_configuration" "main" {
  name              = "${var.project_name}-kafka-config-${replace(var.kafka_version, ".", "-")}"
  kafka_versions    = [var.kafka_version]
  server_properties = <<PROPERTIES
auto.create.topics.enable = true
default.replication.factor = ${var.replication_factor}
min.insync.replicas = ${var.min_insync_replicas}
num.partitions = ${var.num_partitions}
log.retention.hours = ${var.log_retention_hours}
compression.type = gzip
PROPERTIES

  lifecycle {
    create_before_destroy = true
  }
}

# CloudWatch Log Group for MSK
resource "aws_cloudwatch_log_group" "msk" {
  name              = "/aws/msk/${var.project_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-msk-logs"
    Environment = var.environment
  }
}

# Security Group for MSK
# Using CIDR-based rules for Kafka ports - this is secure because:
# 1. MSK is in private subnets (no direct internet access)
# 2. Only specific ports (9092, 9094) are open
# 3. Only VPC resources with explicit Kafka egress rules can connect (ECS, Lambda, EMR)
# 4. Avoids circular dependencies (ECS/Lambda need bootstrap_servers from MSK)
# 5. revoke_rules_on_delete ensures clean deletion without SG deadlocks
resource "aws_security_group" "msk" {
  name        = "${var.project_name}-msk-sg"
  description = "Security group for MSK cluster"
  vpc_id      = var.vpc_id

  # Enable automatic rule cleanup before deletion - prevents circular dependency deadlock
  revoke_rules_on_delete = true

  tags = {
    Name        = "${var.project_name}-msk-sg"
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# CIDR-based ingress rules for Kafka clients
resource "aws_security_group_rule" "msk_ingress_kafka_plaintext" {
  count = length(var.allowed_cidr_blocks) > 0 ? 1 : 0

  type              = "ingress"
  description       = "Kafka plaintext from VPC"
  from_port         = 9092
  to_port           = 9092
  protocol          = "tcp"
  security_group_id = aws_security_group.msk.id
  cidr_blocks       = var.allowed_cidr_blocks
}

resource "aws_security_group_rule" "msk_ingress_kafka_tls" {
  count = length(var.allowed_cidr_blocks) > 0 ? 1 : 0

  type              = "ingress"
  description       = "Kafka TLS from VPC"
  from_port         = 9094
  to_port           = 9094
  protocol          = "tcp"
  security_group_id = aws_security_group.msk.id
  cidr_blocks       = var.allowed_cidr_blocks
}

# Allow inter-broker communication (self-reference)
resource "aws_security_group_rule" "msk_ingress_self" {
  type              = "ingress"
  description       = "Inter-broker communication"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.msk.id
  self              = true
}

# Egress restricted to inter-broker only (self)
resource "aws_security_group_rule" "msk_egress_self" {
  type              = "egress"
  description       = "Inter-broker communication"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.msk.id
  self              = true
}
