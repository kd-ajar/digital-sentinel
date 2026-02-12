# SNS Topic for WikiGuard Data Quality Alerts

resource "aws_sns_topic" "wikiguard_alerts" {
  name = "${var.project_name}-${var.environment}-data-quality-alerts"

  tags = {
    Name        = "${var.project_name}-data-quality-alerts"
    Environment = var.environment
    Purpose     = "Data Quality Alerts"
  }
}

# SNS Topic Policy
resource "aws_sns_topic_policy" "wikiguard_alerts" {
  arn = aws_sns_topic.wikiguard_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowAccountAccess"
        Effect    = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = [
            "sns:Publish",
            "sns:Subscribe",
            "sns:SetTopicAttributes"
          ]
        Resource = aws_sns_topic.wikiguard_alerts.arn
      }
    ]
  })
}

# Data source for AWS account ID
data "aws_caller_identity" "current" {}

# Optional: Create subscription for email notifications
resource "aws_sns_topic_subscription" "email" {
  count     = var.email_endpoint != null ? 1 : 0
  topic_arn = aws_sns_topic.wikiguard_alerts.arn
  protocol  = "email"
  endpoint  = var.email_endpoint

  depends_on = [aws_sns_topic.wikiguard_alerts]
}
