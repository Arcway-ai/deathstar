variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "create_backup_bucket" {
  type = bool
}

variable "backup_bucket_name" {
  type = string
}

variable "force_destroy_backup_bucket" {
  type = bool
}

variable "tags" {
  type = map(string)
}
