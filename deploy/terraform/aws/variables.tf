variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "domain" {
  description = "Custom domain name for the Purveyor service (e.g., purveyor.example.com). Leave empty to use the ALB DNS name with HTTP."
  type        = string
  default     = ""
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

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "enable_redis" {
  description = "Enable ElastiCache Redis for caching and rate limiting"
  type        = bool
  default     = false
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for HTTPS on the ALB. Leave empty when not using HTTPS."
  type        = string
  default     = ""
}

variable "existing_vpc_id" {
  description = "Use an existing VPC ID instead of creating a new one. Leave empty to create a new VPC."
  type        = string
  default     = ""
}

variable "container_cpu" {
  description = "ECS task CPU units (256, 512, 1024, 2048)"
  type        = number
  default     = 512
}

variable "container_memory" {
  description = "ECS task memory in MB"
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of ECS task replicas"
  type        = number
  default     = 1
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

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
