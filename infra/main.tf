# ──────────────────────────────────────────────
# Infra própria do Billing Service
#   - Fila billing-commands (+ DLQ) consumida pelo Billing
#   - Política IAM: consumir a própria fila e publicar em os-saga-replies
# Banco lógico billing_db: Job k8s/jobs/db-bootstrap.yaml (RDS não é público).
# Credenciais do Mercado Pago: GitHub Secrets -> Secret do Kubernetes (pipeline).
# ──────────────────────────────────────────────
terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # terraform init -backend-config="key=billing-service/<env>/terraform.tfstate"
  # backend "s3" {
  #   bucket  = "fiap-officine-terraform-state"
  #   region  = "sa-east-1"
  #   encrypt = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Service     = "billing-service"
      ManagedBy   = "terraform"
      Repository  = "fiap-officine-billing-service"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  prefix      = "${var.project}-${var.environment}"
  replies_arn = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.prefix}-os-saga-replies"
}

resource "aws_sqs_queue" "commands_dlq" {
  name                      = "${local.prefix}-billing-commands-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "commands" {
  name                       = "${local.prefix}-billing-commands"
  visibility_timeout_seconds = 60 # chamadas ao Mercado Pago podem demorar
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.commands_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "commands_dlq" {
  queue_url = aws_sqs_queue.commands_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.commands.arn]
  })
}

data "aws_iam_policy_document" "billing_service" {
  statement {
    sid = "ConsumeOwnQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [aws_sqs_queue.commands.arn]
  }

  statement {
    sid       = "PublishSagaReplies"
    actions   = ["sqs:SendMessage", "sqs:GetQueueUrl"]
    resources = [local.replies_arn]
  }
}

resource "aws_iam_policy" "billing_service" {
  name        = "${local.prefix}-billing-service"
  description = "Billing Service: consome billing-commands e publica em os-saga-replies"
  policy      = data.aws_iam_policy_document.billing_service.json
}

resource "aws_iam_role_policy_attachment" "node" {
  count      = var.node_role_name == "" ? 0 : 1
  role       = var.node_role_name
  policy_arn = aws_iam_policy.billing_service.arn
}
