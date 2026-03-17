data "aws_caller_identity" "current" {}

locals {
  parameter_arns = [
    for name in var.parameter_names :
    "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${startswith(name, "/") ? name : "/${name}"}"
  ]
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.project_name}-instance-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid       = "ReadProviderParameters"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = local.parameter_arns
  }

  statement {
    sid       = "ListArtifactBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.artifact_bucket_name}"]
  }

  statement {
    sid       = "ReadArtifactObjects"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.artifact_bucket_name}/runtime/*"]
  }

  dynamic "statement" {
    for_each = var.backup_bucket_name != "" ? [1] : []
    content {
      sid       = "ListBackupBucket"
      actions   = ["s3:ListBucket"]
      resources = ["arn:aws:s3:::${var.backup_bucket_name}"]
    }
  }

  dynamic "statement" {
    for_each = var.backup_bucket_name != "" ? [1] : []
    content {
      sid       = "ReadWriteBackupObjects"
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = ["arn:aws:s3:::${var.backup_bucket_name}/workspace-backups/*"]
    }
  }
}

resource "aws_iam_role_policy" "inline" {
  name   = "${var.project_name}-instance-inline"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.project_name}-instance-profile"
  role = aws_iam_role.this.name
}
