terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name = "purveyor"
  labels = merge(
    {
      app       = local.name
      managedby = "terraform"
    },
    var.labels
  )
}

# ---------------------------------------------------------------------------
# Enable required APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "vpcaccess.googleapis.com",
    "secretmanager.googleapis.com",
    "redis.googleapis.com",
    "compute.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# VPC + Serverless VPC Connector
# ---------------------------------------------------------------------------

resource "google_compute_network" "main" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "main" {
  name          = "${local.name}-subnet"
  ip_cidr_range = "10.0.0.0/24"
  region        = var.region
  network       = google_compute_network.main.id
}

resource "google_vpc_access_connector" "main" {
  name          = "${local.name}-connector"
  region        = var.region
  ip_cidr_range = "10.8.0.0/28"
  network       = google_compute_network.main.name
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Cloud SQL Postgres with PostGIS
# ---------------------------------------------------------------------------

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = local.name
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.db_tier

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }

    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = false
  depends_on          = [google_project_service.apis]
}

resource "google_sql_database" "main" {
  name     = "purveyor"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "main" {
  name     = "purveyor"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

# ---------------------------------------------------------------------------
# Memorystore Redis (optional)
# ---------------------------------------------------------------------------

resource "google_redis_instance" "main" {
  count          = var.enable_redis ? 1 : 0
  name           = local.name
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.region

  authorized_network = google_compute_network.main.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  labels     = local.labels
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

resource "random_bytes" "fernet_key" {
  length = 32
}

resource "google_secret_manager_secret" "skyfi_api_key" {
  secret_id = "${local.name}-skyfi-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "skyfi_api_key" {
  secret      = google_secret_manager_secret.skyfi_api_key.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "confirmation_secret_key" {
  secret_id = "${local.name}-confirmation-secret-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "confirmation_secret_key" {
  secret      = google_secret_manager_secret.confirmation_secret_key.id
  secret_data = base64encode(random_bytes.fernet_key.base64)

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# ---------------------------------------------------------------------------
# Service Account for Cloud Run
# ---------------------------------------------------------------------------

resource "google_service_account" "run" {
  account_id   = local.name
  display_name = "Purveyor Cloud Run Service Account"
}

resource "google_project_iam_member" "run_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "skyfi_api_key" {
  secret_id = google_secret_manager_secret.skyfi_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "confirmation_secret_key" {
  secret_id = google_secret_manager_secret.confirmation_secret_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run Service
# ---------------------------------------------------------------------------

locals {
  db_url    = "postgresql+asyncpg://purveyor:${random_password.db.result}@/purveyor?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
  redis_url = var.enable_redis ? "redis://${google_redis_instance.main[0].host}:6379" : ""
}

resource "google_cloud_run_v2_service" "main" {
  name     = local.name
  location = var.region

  template {
    service_account = google_service_account.run.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.main.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = "${var.image_repository}:${var.image_tag}"

      resources {
        limits = {
          cpu    = var.container_cpu
          memory = var.container_memory
        }
      }

      ports {
        container_port = 8000
      }

      env {
        name  = "DATABASE_URL"
        value = local.db_url
      }
      env {
        name  = "CACHE_BACKEND"
        value = var.enable_redis ? "redis" : "memory"
      }
      env {
        name  = "REDIS_URL"
        value = local.redis_url
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "CONFIRMATION_BASE_URL"
        value = "https://${var.domain}"
      }
      env {
        name  = "SENTRY_DSN"
        value = var.sentry_dsn
      }

      env {
        name = "SKYFI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.skyfi_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "CONFIRMATION_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.confirmation_secret_key.secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 30
        period_seconds        = 30
      }
    }
  }

  labels     = local.labels
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  location = google_cloud_run_v2_service.main.location
  name     = google_cloud_run_v2_service.main.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
