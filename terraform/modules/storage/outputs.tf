output "artifact_bucket_name" {
  value = aws_s3_bucket.artifacts.id
}

output "backup_bucket_name" {
  value = local.effective_backup_bucket_name
}
