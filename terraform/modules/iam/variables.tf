variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "parameter_names" {
  type = list(string)
}

variable "artifact_bucket_name" {
  type = string
}

variable "backup_bucket_name" {
  type = string
}

variable "tags" {
  type = map(string)
}
