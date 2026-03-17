resource "aws_instance" "this" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [var.security_group_id]
  iam_instance_profile        = var.iam_instance_profile_name
  associate_public_ip_address = var.associate_public_ip_address
  user_data_base64            = var.user_data_base64
  user_data_replace_on_change = true

  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  tags = merge(var.tags, {
    Name = var.name
  })
}

resource "aws_ebs_volume" "workspace" {
  availability_zone = var.availability_zone
  encrypted         = true
  size              = var.data_volume_size_gb
  type              = "gp3"

  tags = merge(var.tags, {
    Name = "${var.name}-workspace"
  })
}

resource "aws_volume_attachment" "workspace" {
  device_name  = "/dev/sdf"
  volume_id    = aws_ebs_volume.workspace.id
  instance_id  = aws_instance.this.id
  force_detach = true
}
