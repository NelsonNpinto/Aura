// AWS profile for AURA (Phase 5.5, optional — HC-4).
//
// Scope is deliberately tiny and stays inside the AWS free plan:
//   * an OIDC role GitHub Actions can assume to call Bedrock (no static keys anywhere);
//   * one S3 bucket for eval artifacts, private and versioned.
//
// The ECS Fargate module is validated and planned in CI only and is never applied: running it
// would leave billable resources behind, which the $0 constraint forbids (§A3). Bedrock
// AgentCore is a paid-plan alternative and is documented in docs/COSTS.md, not deployed.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "AWS region (US East keeps Bedrock next to the rest of the stack)"
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = "owner/name of the repository allowed to assume the role"
  type        = string
  default     = "NelsonNpinto/Aura"
}

variable "artifacts_bucket" {
  description = "S3 bucket for eval artifacts; must be globally unique"
  type        = string
  default     = "aura-eval-artifacts"
}

data "aws_caller_identity" "current" {}

// GitHub's OIDC provider. Create it once per account; import it if it already exists.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    // Only this repository's workflows, and only on the default branch.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_bedrock" {
  name               = "aura-github-bedrock"
  description        = "GitHub Actions OIDC role: Bedrock inference and eval artifacts"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid    = "InvokeFoundationModels"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:ListFoundationModels",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "EvalArtifacts"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
  }
}

resource "aws_iam_role_policy" "bedrock_invoke" {
  name   = "aura-bedrock-invoke"
  role   = aws_iam_role.github_bedrock.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.artifacts_bucket}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

// Eval artifacts are evidence, not archives: 90 days is enough and keeps storage free-tier sized.
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-eval-artifacts"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

output "role_arn" {
  description = "Set this as AWS_ROLE_ARN in the GitHub environment"
  value       = aws_iam_role.github_bedrock.arn
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}
