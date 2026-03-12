variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region to deploy into"
  type        = string
  default     = "us-central1"
}

variable "domain" {
  description = "Domain name for the Purveyor service (e.g., purveyor.example.com)"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g., v1.0.0 or latest)"
  type        = string
  default     = "latest"
}

variable "image_repository" {
  description = "Docker image repository (e.g., ghcr.io/your-org/purveyor)"
  type        = string
  default     = "ghcr.io/your-org/purveyor"
}

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "enable_redis" {
  description = "Enable Memorystore Redis for caching and rate limiting"
  type        = bool
  default     = false
}

variable "min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero)"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 10
}

variable "container_memory" {
  description = "Cloud Run container memory (e.g., 512Mi, 1Gi)"
  type        = string
  default     = "512Mi"
}

variable "container_cpu" {
  description = "Cloud Run container CPU (e.g., 1, 2)"
  type        = string
  default     = "1"
}

variable "log_level" {
  description = "Purveyor log level"
  type        = string
  default     = "info"
}

variable "sentry_dsn" {
  description = "Optional Sentry DSN for error tracking"
  type        = string
  default     = ""
  sensitive   = true
}

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}
