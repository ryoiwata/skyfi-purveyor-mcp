# No custom domain for now — we'll use the ALB DNS name directly
domain = ""
acm_certificate_arn = ""

# Your ECR image
image_repository = "496780244141.dkr.ecr.us-east-1.amazonaws.com/purveyor"
image_tag        = "v1.1.0"

# AWS region
region = "us-east-1"

# Database
db_instance_class = "db.t3.micro"

# No Redis for now
enable_redis = false

# ECS task sizing (minimal)
container_cpu    = 512
container_memory = 1024
desired_count    = 1

tags = {
  Environment = "production"
  Team        = "platform"
}
