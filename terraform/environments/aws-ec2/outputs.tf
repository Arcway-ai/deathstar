output "instance_id" {
  value = module.instance.instance_id
}

output "region" {
  value = var.aws_region
}

output "remote_api_port" {
  value = 8080
}

output "tailscale_enabled" {
  value = var.enable_tailscale
}

output "tailscale_hostname" {
  value = var.enable_tailscale ? local.effective_tailscale_hostname : null
}

output "ssh_user" {
  value = local.ssh_user
}

output "workspace_volume_id" {
  value = module.instance.workspace_volume_id
}

output "artifact_bucket_name" {
  value = module.storage.artifact_bucket_name
}

output "backup_bucket_name" {
  value = module.storage.backup_bucket_name
}
