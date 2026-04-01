###############################################################################
# Slack AI Assistant Infrastructure
#
# Deploys:
#   - Lambda function (Slack event handler)
#   - API Gateway (HTTP API for Slack events)
#   - S3 bucket (knowledge base documents)
#   - DynamoDB table (conversation caching)
#   - SSM Parameter Store (secrets: API keys)
#   - IAM roles + policies
#   - CloudWatch log groups + alarms
###############################################################################

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "Three-Moons-Network"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name"
  type        = string
  default     = "default"
}

variable "project_name" {
  description = "Project identifier used in resource naming"
  type        = string
  default     = "slack-ai-assistant"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "slack_bot_token" {
  description = "Slack bot token"
  type        = string
  sensitive   = true
}

variable "slack_signing_secret" {
  description = "Slack app signing secret"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key"
  type        = string
  sensitive   = true
}

variable "anthropic_model" {
  description = "Claude model to use"
  type        = string
  default     = "claude-sonnet-4-20250514"
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}

locals {
  prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# SSM Parameter Store — Secrets
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "slack_bot_token" {
  name        = "/${var.project_name}/${var.environment}/slack-bot-token"
  description = "Slack bot token"
  type        = "SecureString"
  value       = var.slack_bot_token

  tags = {
    Name = "${local.prefix}-slack-bot-token"
  }
}

resource "aws_ssm_parameter" "slack_signing_secret" {
  name        = "/${var.project_name}/${var.environment}/slack-signing-secret"
  description = "Slack app signing secret"
  type        = "SecureString"
  value       = var.slack_signing_secret

  tags = {
    Name = "${local.prefix}-slack-signing-secret"
  }
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/${var.project_name}/${var.environment}/anthropic-api-key"
  description = "Anthropic API key"
  type        = "SecureString"
  value       = var.anthropic_api_key

  tags = {
    Name = "${local.prefix}-anthropic-api-key"
  }
}

# ---------------------------------------------------------------------------
# S3 Bucket — Knowledge Base
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "knowledge_base" {
  bucket = "${local.prefix}-docs-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${local.prefix}-docs"
  }
}

resource "aws_s3_bucket_versioning" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# DynamoDB Table — Conversation Cache
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "conversations" {
  name             = "${local.prefix}-conversations"
  billing_mode     = "PAY_PER_REQUEST" # Auto-scaling for small volumes
  hash_key         = "conversation_id"
  range_key        = "timestamp"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "conversation_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  # TTL for automatic cleanup (30 days)
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "${local.prefix}-conversations"
  }
}

# ---------------------------------------------------------------------------
# IAM Role and Policies
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.prefix}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  # SSM Parameter Store — read secrets
  statement {
    actions = ["ssm:GetParameter"]
    resources = [
      aws_ssm_parameter.slack_bot_token.arn,
      aws_ssm_parameter.slack_signing_secret.arn,
      aws_ssm_parameter.anthropic_api_key.arn,
    ]
  }

  # S3 — read knowledge base documents
  statement {
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.knowledge_base.arn,
      "${aws_s3_bucket.knowledge_base.arn}/*",
    ]
  }

  # DynamoDB — read/write conversations
  statement {
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [aws_dynamodb_table.conversations.arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.prefix}-lambda-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# ---------------------------------------------------------------------------
# CloudWatch Log Groups
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.prefix}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${local.prefix}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# Lambda Function
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "handler" {
  function_name = local.prefix
  description   = "Slack AI Assistant — ${var.environment} environment"
  runtime       = "python3.11"
  handler       = "handler.lambda_handler"
  memory_size   = var.lambda_memory
  timeout       = var.lambda_timeout
  role          = aws_iam_role.lambda.arn

  filename         = "${path.module}/../dist/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/lambda.zip")

  environment {
    variables = {
      ENVIRONMENT          = var.environment
      ANTHROPIC_MODEL      = var.anthropic_model
      LOG_LEVEL            = var.environment == "prod" ? "WARNING" : "INFO"
      SLACK_BOT_TOKEN      = var.slack_bot_token
      SLACK_SIGNING_SECRET = var.slack_signing_secret
      ANTHROPIC_API_KEY    = var.anthropic_api_key
      S3_BUCKET            = aws_s3_bucket.knowledge_base.id
      S3_PREFIX            = "docs/"
      DYNAMODB_TABLE       = aws_dynamodb_table.conversations.name
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda,
  ]
}

# ---------------------------------------------------------------------------
# API Gateway — HTTP API
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"
  description   = "Slack AI Assistant"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "events" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /events"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 100
    throttling_burst_limit = 200
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      method         = "$context.httpMethod"
      status         = "$context.status"
      latency        = "$context.responseLatency"
      integrationErr = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.prefix}-lambda-errors"
  alarm_description   = "Lambda error rate exceeded"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.handler.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name          = "${local.prefix}-lambda-duration"
  alarm_description   = "Lambda duration exceeded threshold"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p99"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.lambda_timeout * 1000 * 0.8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.handler.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "dynamodb_capacity" {
  alarm_name          = "${local.prefix}-dynamodb-throttle"
  alarm_description   = "DynamoDB read/write capacity throttled"
  namespace           = "AWS/DynamoDB"
  metric_name         = "ConsumedWriteCapacityUnits"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.conversations.name
  }
}
