# Secrets Manager Module

resource "aws_secretsmanager_secret" "slack_bot_token" {
  name        = "${var.project_name}/slack-bot-token"
  description = "Slack Bot Token for Data Quality alerts"

  tags = {
    Name        = "${var.project_name}-slack-bot-token"
    Environment = var.environment
  }
}

# Note: The actual secret value will be set via CLI after terraform apply:
# aws secretsmanager put-secret-value --secret-id wikiguard/slack-bot-token --secret-string "xoxb-your-token"
