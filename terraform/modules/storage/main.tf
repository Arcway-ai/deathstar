data "aws_caller_identity" "current" {}

locals {
  base_name = substr(
    replace(lower("${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"), "_", "-"),
    0,
    48,
  )

  artifact_bucket_name         = "${local.base_name}-artifacts"
  generated_backup_bucket_name = "${local.base_name}-backups"
  effective_backup_bucket_name = var.create_backup_bucket ? (
    var.backup_bucket_name != "" ? var.backup_bucket_name : local.generated_backup_bucket_name
    ) : (
    var.backup_bucket_name != "" ? var.backup_bucket_name : null
  )
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = local.artifact_bucket_name
  force_destroy = true

  tags = merge(var.tags, {
    Name = local.artifact_bucket_name
  })
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

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-runtime-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

resource "aws_s3_bucket" "backups" {
  count         = var.create_backup_bucket ? 1 : 0
  bucket        = local.effective_backup_bucket_name
  force_destroy = var.force_destroy_backup_bucket

  tags = merge(var.tags, {
    Name = local.effective_backup_bucket_name
  })
}

resource "aws_s3_bucket_public_access_block" "backups" {
  count                   = var.create_backup_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.backups[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  count  = var.create_backup_bucket ? 1 : 0
  bucket = aws_s3_bucket.backups[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  count  = var.create_backup_bucket ? 1 : 0
  bucket = aws_s3_bucket.backups[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
