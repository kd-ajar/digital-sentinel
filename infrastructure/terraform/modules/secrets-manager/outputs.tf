# Secrets Manager Outputs

output "slack_bot_token_secret_arn" {
  description = "ARN of the Slack Bot Token secret"
  value       = aws_secretsmanager_secret.slack_bot_token.arn
}

output "slack_bot_token_secret_name" {
  description = "Name of the Slack Bot Token secret"
  value       = aws_secretsmanager_secret.slack_bot_token.name
}
