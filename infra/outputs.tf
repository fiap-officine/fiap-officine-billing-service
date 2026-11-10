output "commands_queue_url" {
  value = aws_sqs_queue.commands.url
}

output "commands_queue_arn" {
  value = aws_sqs_queue.commands.arn
}

output "commands_dlq_arn" {
  description = "DLQ monitorada pelo alerta do New Relic"
  value       = aws_sqs_queue.commands_dlq.arn
}

output "iam_policy_arn" {
  value = aws_iam_policy.billing_service.arn
}
