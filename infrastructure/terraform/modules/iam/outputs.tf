output "ecs_execution_role_arn" {
  description = "ECS task execution role ARN"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ECS task role ARN"
  value       = aws_iam_role.ecs_task.arn
}

output "lambda_execution_role_arn" {
  description = "Lambda execution role ARN"
  value       = aws_iam_role.lambda_execution.arn
}

output "ecs_scaler_role_arn" {
  description = "ECS scaler Lambda role ARN"
  value       = aws_iam_role.ecs_scaler.arn
}

output "eventbridge_role_arn" {
  description = "EventBridge role ARN"
  value       = aws_iam_role.eventbridge.arn
}

output "emr_service_role_arn" {
  description = "EMR service role ARN"
  value       = aws_iam_role.emr_service.arn
}

output "emr_instance_profile_arn" {
  description = "EMR EC2 instance profile ARN"
  value       = aws_iam_instance_profile.emr_ec2.arn
}

output "emr_ec2_role_arn" {
  description = "EMR EC2 role ARN"
  value       = aws_iam_role.emr_ec2.arn
}
