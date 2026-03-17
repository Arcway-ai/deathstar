variable "name" {
  type = string
}

variable "ami_id" {
  type = string
}

variable "instance_type" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "availability_zone" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "iam_instance_profile_name" {
  type = string
}

variable "associate_public_ip_address" {
  type = bool
}

variable "root_volume_size_gb" {
  type = number
}

variable "data_volume_size_gb" {
  type = number
}

variable "user_data_base64" {
  type = string
}

variable "tags" {
  type = map(string)
}
