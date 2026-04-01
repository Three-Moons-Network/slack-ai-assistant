output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "events_url" {
  description = "Full URL for Slack event subscriptions"
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/events"
}

output "s3_bucket_name" {
  description = "S3 bucket for knowledge base documents"
  value       = aws_s3_bucket.knowledge_base.id
}

output "dynamodb_table_name" {
  description = "DynamoDB table for conversation caching"
  value       = aws_dynamodb_table.conversations.name
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.handler.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.handler.arn
}

output "cloudwatch_log_group" {
  description = "Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.lambda.name
}
