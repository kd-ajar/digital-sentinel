# ECS Fargate Module for Peak Hours

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name        = "${var.project_name}-cluster"
    Environment = var.environment
  }
}

# ECR Repository
resource "aws_ecr_repository" "ingest" {
  name                 = "${var.project_name}/ingest"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "${var.project_name}-ingest"
    Environment = var.environment
  }
}

# ECS Task Definition
resource "aws_ecs_task_definition" "ingest" {
  family                   = "${var.project_name}-ingest"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name  = "ingest-consumer"
      image = "${aws_ecr_repository.ingest.repository_url}:${var.image_tag}"
      
      environment = [
        {
          name  = "KAFKA_BOOTSTRAP_SERVERS"
          value = var.kafka_bootstrap_servers
        },
        {
          name  = "ALLOWLIST_PATH"
          value = "/app/config/entity-allowlist.yaml"
        },
        {
          name  = "USER_AGENT"
          value = "WikiGuard/1.0 ECS"
        },
        {
          name  = "KAFKA_SECURITY_PROTOCOL"
          value = "SSL"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ingest"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "echo healthy"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name        = "${var.project_name}-ingest-task"
    Environment = var.environment
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}/ingest"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-ecs-logs"
    Environment = var.environment
  }
}

# ECS Service
resource "aws_ecs_service" "ingest" {
  name            = "${var.project_name}-ingest-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ingest.arn
  desired_count   = var.initial_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  tags = {
    Name        = "${var.project_name}-ingest-service"
    Environment = var.environment
  }
}

# Security Group for ECS Tasks (SSE Consumer)
# Needs: Outbound to Wikimedia (HTTPS), Outbound to Kafka (MSK)
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks-sg"
  description = "Security group for ECS tasks"
  vpc_id      = var.vpc_id

  # Enable automatic rule cleanup before deletion
  revoke_rules_on_delete = true

  tags = {
    Name        = "${var.project_name}-ecs-tasks-sg"
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Egress to Wikimedia EventStreams (HTTPS)
resource "aws_security_group_rule" "ecs_egress_https" {
  type              = "egress"
  description       = "HTTPS for Wikimedia SSE and AWS services"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.ecs_tasks.id
  cidr_blocks       = ["0.0.0.0/0"]  # Wikimedia + AWS APIs
}

# Egress to Kafka (MSK) - using VPC CIDR for specific ports
resource "aws_security_group_rule" "ecs_egress_kafka_plaintext" {
  type              = "egress"
  description       = "Kafka plaintext to MSK"
  from_port         = 9092
  to_port           = 9092
  protocol          = "tcp"
  security_group_id = aws_security_group.ecs_tasks.id
  cidr_blocks       = [var.vpc_cidr]
}

resource "aws_security_group_rule" "ecs_egress_kafka_tls" {
  type              = "egress"
  description       = "Kafka TLS to MSK"
  from_port         = 9094
  to_port           = 9094
  protocol          = "tcp"
  security_group_id = aws_security_group.ecs_tasks.id
  cidr_blocks       = [var.vpc_cidr]
}

# NOTE: MSK owns its ingress rules referencing this ECS SG
