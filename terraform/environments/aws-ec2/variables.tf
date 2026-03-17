variable "aws_region" {
  type    = string
  default = "us-west-1"
}

variable "project_name" {
  type    = string
  default = "deathstar"
}

variable "instance_type" {
  type    = string
  default = "t3.large"
}

variable "root_volume_size_gb" {
  type    = number
  default = 30
}

variable "data_volume_size_gb" {
  type    = number
  default = 200
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  type    = string
  default = "10.42.10.0/24"
}

variable "associate_public_ip_address" {
  type    = bool
  default = true
}

variable "enable_web_ui" {
  type    = bool
  default = false
}

variable "web_ui_port" {
  type    = number
  default = 8443
}

variable "web_ui_allowed_cidrs" {
  type    = list(string)
  default = []
}

variable "openai_api_key_parameter_name" {
  type    = string
  default = "/deathstar/providers/openai/api_key"
}

variable "anthropic_api_key_parameter_name" {
  type    = string
  default = "/deathstar/providers/anthropic/api_key"
}

variable "google_api_key_parameter_name" {
  type    = string
  default = "/deathstar/providers/google/api_key"
}

variable "vertex_service_account_key_parameter_name" {
  type    = string
  default = "/deathstar/providers/vertex/service_account_key"
}

variable "vertex_project_id" {
  type    = string
  default = ""
}

variable "vertex_location" {
  type    = string
  default = "us-central1"
}

variable "default_vertex_model" {
  type    = string
  default = "gemini-2.0-flash"
}

variable "api_token_parameter_name" {
  type    = string
  default = "/deathstar/api_token"
}

variable "github_token_parameter_name" {
  type    = string
  default = "/deathstar/integrations/github/token"
}

variable "tailscale_auth_key_parameter_name" {
  type    = string
  default = "/deathstar/integrations/tailscale/auth_key"
}

variable "enable_tailscale" {
  type    = bool
  default = true
}

variable "enable_tailscale_ssh" {
  type    = bool
  default = true
}

variable "tailscale_hostname" {
  type    = string
  default = ""
}

variable "tailscale_advertise_tags" {
  type    = list(string)
  default = []
}

variable "create_backup_bucket" {
  type    = bool
  default = false
}

variable "backup_bucket_name" {
  type    = string
  default = ""
}

variable "force_destroy_backup_bucket" {
  type    = bool
  default = false
}

variable "default_openai_model" {
  type    = string
  default = "gpt-4o-mini"
}

variable "default_anthropic_model" {
  type    = string
  default = "claude-sonnet-4-5-20250514"
}

variable "default_google_model" {
  type    = string
  default = "gemini-2.0-flash"
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "git_author_name" {
  type    = string
  default = "DeathStar"
}

variable "git_author_email" {
  type    = string
  default = "deathstar@local"
}
