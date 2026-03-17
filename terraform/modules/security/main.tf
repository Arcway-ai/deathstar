resource "aws_security_group" "this" {
  name        = "${var.project_name}-sg"
  description = "DeathStar remote runtime security group"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.project_name}-sg"
  })
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Allow outbound access for AWS APIs, package mirrors, git remotes, and AI providers."
}

resource "aws_vpc_security_group_ingress_rule" "web_ui" {
  for_each = var.enable_web_ui ? toset(var.web_ui_allowed_cidrs) : toset([])

  security_group_id = aws_security_group.this.id
  ip_protocol       = "tcp"
  from_port         = var.web_ui_port
  to_port           = var.web_ui_port
  cidr_ipv4         = each.value
  description       = "Optional restricted web UI ingress."
}
