output "service_url" {
  description = "Public URL of the Purveyor service"
  value       = "https://${var.domain}"
}

output "alb_dns_name" {
  description = "ALB DNS name (point your domain's CNAME here)"
  value       = aws_lb.main.dns_name
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint"
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for Purveyor"
  value       = aws_cloudwatch_log_group.main.name
}

output "ssm_skyfi_api_key_path" {
  description = "SSM parameter path for SKYFI_API_KEY (update this with your key)"
  value       = aws_ssm_parameter.skyfi_api_key.name
}
