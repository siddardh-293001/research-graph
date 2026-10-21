terraform {
  required_version = ">= 1.5, < 2.0"
  required_providers {
    render = {
      source  = "render-oss/render"
      version = "1.9.1"
    }
  }
}

# Credentials come from RENDER_API_KEY, never from this file or tfvars.
provider "render" {
  owner_id = var.workspace_id
}

variable "workspace_id" {
  type        = string
  description = "Confirmed Render workspace; My Workspace is tea-dbb5bjnavr4c73fvbs30."
}

variable "repository_url" {
  type        = string
  description = "Git repository containing the staged public serving release."
  default     = "https://github.com/siddardh-293001/research-graph"
}

resource "render_web_service" "demo" {
  name              = "researchgraph"
  plan              = "free"
  region            = "singapore"
  num_instances     = 1
  health_check_path = "/readyz"
  runtime_source = {
    docker = {
      repo_url        = var.repository_url
      branch          = "main"
      auto_deploy     = false
      dockerfile_path = "./Dockerfile"
      context         = "."
    }
  }
  env_vars = {
    RESEARCHGRAPH_RELEASE = { value = "/app/release" }
    OMP_NUM_THREADS       = { value = "1" }
    OPENBLAS_NUM_THREADS  = { value = "1" }
  }
  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.plan == "free"
      error_message = "Only Render's free compute plan is authorized."
    }
  }
}

output "public_url" {
  value = render_web_service.demo.url
}
