data "aws_ssm_parameter" "ubuntu_2404" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  repo_root                    = abspath("${path.module}/../../..")
  ssh_user                     = "ubuntu"
  effective_tailscale_hostname = trimspace(var.tailscale_hostname) != "" ? trimspace(var.tailscale_hostname) : var.project_name

  runtime_files = toset(concat(
    [
      "pyproject.toml",
      "README.md",
      "alembic.ini",
      "docker/.dockerignore",
      "docker/docker-compose.yml",
      "docker/control-api.Dockerfile",
      "docker/entrypoint.sh",
    ],
    [for file in fileset(local.repo_root, "alembic/**") : file if !can(regex("__pycache__", file))],
    [for file in fileset(local.repo_root, "cli/**") : file if !can(regex("__pycache__", file))],
    [for file in fileset(local.repo_root, "scripts/**") : file],
    [for file in fileset(local.repo_root, "server/**") : file if !can(regex("__pycache__", file))],
    [for file in fileset(local.repo_root, "shared/**") : file if !can(regex("__pycache__", file))],
    [for file in fileset(local.repo_root, "plugins/**") : file],
    [for file in fileset(local.repo_root, "web/{package.json,package-lock.json,index.html,vite.config.ts,tsconfig.json,tsconfig.app.json}") : file],
    [for file in fileset(local.repo_root, "web/public/**") : file],
    [for file in fileset(local.repo_root, "web/src/**") : file],
  ))

  runtime_revision = sha256(join("", [
    for file in sort(tolist(local.runtime_files)) :
    filebase64sha256("${local.repo_root}/${file}")
  ]))

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Service   = "deathstar"
  }
}

module "network" {
  source             = "../../modules/network"
  project_name       = var.project_name
  vpc_cidr           = var.vpc_cidr
  public_subnet_cidr = var.public_subnet_cidr
  tags               = local.tags
}

module "security" {
  source               = "../../modules/security"
  project_name         = var.project_name
  vpc_id               = module.network.vpc_id
  enable_web_ui        = var.enable_web_ui
  web_ui_port          = var.web_ui_port
  web_ui_allowed_cidrs = var.web_ui_allowed_cidrs
  tags                 = local.tags
}

module "storage" {
  source                      = "../../modules/storage"
  project_name                = var.project_name
  aws_region                  = var.aws_region
  create_backup_bucket        = var.create_backup_bucket
  backup_bucket_name          = var.backup_bucket_name
  force_destroy_backup_bucket = var.force_destroy_backup_bucket
  tags                        = local.tags
}

resource "aws_s3_object" "runtime_files" {
  for_each = local.runtime_files

  bucket = module.storage.artifact_bucket_name
  key    = "runtime/${local.runtime_revision}/${each.value}"
  source = "${local.repo_root}/${each.value}"
  etag   = filemd5("${local.repo_root}/${each.value}")
}

locals {
  rendered_prepare_workspace_volume = templatefile(
    "${local.repo_root}/bootstrap/files/prepare-workspace-volume.sh.tftpl",
    {},
  )

  rendered_render_runtime_env = templatefile(
    "${local.repo_root}/bootstrap/files/render-runtime-env.sh.tftpl",
    {
      aws_region                       = var.aws_region
      backup_bucket_name               = module.storage.backup_bucket_name != null ? module.storage.backup_bucket_name : ""
      log_level                        = var.log_level
      default_openai_model             = var.default_openai_model
      default_anthropic_model          = var.default_anthropic_model
      default_google_model             = var.default_google_model
      default_vertex_model             = var.default_vertex_model
      vertex_project_id                = var.vertex_project_id
      vertex_location                  = var.vertex_location
      git_author_name                  = var.git_author_name
      git_author_email                 = var.git_author_email
      enable_tailscale                 = var.enable_tailscale
      tailscale_hostname               = local.effective_tailscale_hostname
      ssh_user                         = local.ssh_user
      enable_web_ui                    = var.enable_web_ui
      api_token_parameter_name         = var.api_token_parameter_name
      openai_api_key_parameter_name    = var.openai_api_key_parameter_name
      anthropic_api_key_parameter_name = var.anthropic_api_key_parameter_name
      google_api_key_parameter_name    = var.google_api_key_parameter_name
      vertex_sa_key_parameter_name     = var.vertex_service_account_key_parameter_name
      github_token_parameter_name      = var.github_token_parameter_name
    },
  )

  rendered_install_tailscale = templatefile(
    "${local.repo_root}/bootstrap/files/install-tailscale.sh.tftpl",
    {
      enable_tailscale = var.enable_tailscale
    },
  )

  rendered_configure_tailscale = templatefile(
    "${local.repo_root}/bootstrap/files/configure-tailscale.sh.tftpl",
    {
      enable_tailscale                  = var.enable_tailscale
      enable_tailscale_ssh              = var.enable_tailscale_ssh
      aws_region                        = var.aws_region
      tailscale_auth_key_parameter_name = var.tailscale_auth_key_parameter_name
      tailscale_hostname                = local.effective_tailscale_hostname
      tailscale_advertise_tags          = join(",", var.tailscale_advertise_tags)
    },
  )

  rendered_sync_runtime = templatefile(
    "${local.repo_root}/bootstrap/files/sync-runtime.sh.tftpl",
    {
      aws_region           = var.aws_region
      artifact_bucket_name = module.storage.artifact_bucket_name
    },
  )

  rendered_start_runtime = file("${local.repo_root}/bootstrap/files/start-runtime.sh")
  rendered_stop_runtime  = file("${local.repo_root}/bootstrap/files/stop-runtime.sh")

  rendered_service_unit = templatefile(
    "${local.repo_root}/bootstrap/files/deathstar-runtime.service.tftpl",
    {},
  )

  rendered_cloud_init = templatefile(
    "${local.repo_root}/bootstrap/cloud-init.yaml.tftpl",
    {
      prepare_workspace_volume = local.rendered_prepare_workspace_volume
      render_runtime_env       = local.rendered_render_runtime_env
      install_tailscale        = local.rendered_install_tailscale
      configure_tailscale      = local.rendered_configure_tailscale
      sync_runtime             = local.rendered_sync_runtime
      start_runtime            = local.rendered_start_runtime
      stop_runtime             = local.rendered_stop_runtime
      service_unit             = local.rendered_service_unit
    },
  )
}

module "iam" {
  source       = "../../modules/iam"
  project_name = var.project_name
  aws_region   = var.aws_region
  parameter_names = compact([
    var.api_token_parameter_name,
    var.openai_api_key_parameter_name,
    var.anthropic_api_key_parameter_name,
    var.google_api_key_parameter_name,
    var.vertex_service_account_key_parameter_name,
    var.github_token_parameter_name,
    var.enable_tailscale ? var.tailscale_auth_key_parameter_name : "",
  ])
  artifact_bucket_name = module.storage.artifact_bucket_name
  backup_bucket_name   = module.storage.backup_bucket_name != null ? module.storage.backup_bucket_name : ""
  tags                 = local.tags
}

module "instance" {
  source                      = "../../modules/instance"
  depends_on                  = [aws_s3_object.runtime_files]
  name                        = var.project_name
  ami_id                      = data.aws_ssm_parameter.ubuntu_2404.value
  instance_type               = var.instance_type
  subnet_id                   = module.network.subnet_id
  availability_zone           = module.network.availability_zone
  security_group_id           = module.security.security_group_id
  iam_instance_profile_name   = module.iam.instance_profile_name
  associate_public_ip_address = var.associate_public_ip_address
  root_volume_size_gb         = var.root_volume_size_gb
  data_volume_size_gb         = var.data_volume_size_gb
  user_data_base64            = base64gzip(local.rendered_cloud_init)
  tags                        = local.tags
}
