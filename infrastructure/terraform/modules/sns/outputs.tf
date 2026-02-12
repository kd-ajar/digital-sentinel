output "topic_arn" {
  description = "ARN of the WikiGuard SNS topic"
  value       = aws_sns_topic.wikiguard_alerts.arn
}

output "topic_name" {
  description = "Name of the WikiGuard SNS topic"
  value       = aws_sns_topic.wikiguard_alerts.name
}

output "topic_id" {
  description = "ID of the WikiGuard SNS topic"
  value       = aws_sns_topic.wikiguard_alerts.id
}

output "display_name" {
  description = "Display name of the WikiGuard SNS topic"
  value       = aws_sns_topic.wikiguard_alerts.display_name
}