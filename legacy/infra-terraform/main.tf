terraform {
  required_version = ">= 1.6.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.6"
    }
  }
}

provider "docker" {}

variable "postgres_password" {
  type        = string
  sensitive   = true
  description = "Development database password; pass with TF_VAR_postgres_password."
  validation {
    condition     = length(var.postgres_password) >= 24
    error_message = "Use at least 24 characters."
  }
}

resource "docker_image" "pgvector" {
  name         = "pgvector/pgvector:pg16"
  keep_locally = true
}

resource "docker_volume" "database" {
  name = "aura-terraform-database"
}

resource "docker_network" "workspace" {
  name     = "aura-terraform-network"
  internal = true
}

resource "docker_container" "database" {
  name  = "aura-terraform-db"
  image = docker_image.pgvector.image_id
  env = [
    "POSTGRES_USER=aura",
    "POSTGRES_DB=aura",
    "POSTGRES_PASSWORD=${var.postgres_password}",
  ]
  ports {
    internal = 5432
    external = 5435
    ip       = "127.0.0.1"
  }
  volumes {
    volume_name    = docker_volume.database.name
    container_path = "/var/lib/postgresql/data"
  }
  networks_advanced {
    name = docker_network.workspace.name
  }
  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U aura -d aura"]
    interval = "10s"
    timeout  = "5s"
    retries  = 10
  }
}

output "database_address" {
  value = "127.0.0.1:5435"
}
