variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "enable_web_ui" {
  type = bool
}

variable "web_ui_port" {
  type = number
}

variable "web_ui_allowed_cidrs" {
  type = list(string)
}

variable "tags" {
  type = map(string)
}
