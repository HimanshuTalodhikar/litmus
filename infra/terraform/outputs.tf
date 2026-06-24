output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "ecs_cluster_name" {
  description = "ECS Cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS Cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "ecs_task_execution_role_arn" {
  description = "ECS Task Execution Role ARN"
  value       = aws_iam_role.ecs_execution_role.arn
}

output "ecs_task_role_arn" {
  description = "ECS Task Role ARN"
  value       = aws_iam_role.ecs_task_role.arn
}

output "db_instance_endpoint" {
  description = "RDS PostgreSQL instance endpoint"
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "db_instance_address" {
  description = "RDS PostgreSQL instance address"
  value       = aws_db_instance.postgres.address
}

output "db_name" {
  description = "RDS database name"
  value       = aws_db_instance.postgres.db_name
}

output "db_username" {
  description = "RDS database username"
  value       = aws_db_instance.postgres.username
}

output "redis_cluster_endpoint" {
  description = "ElastiCache Redis cluster endpoint"
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}


output "alb_dns_name" {
  description = "ALB DNS name for accessing the application"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB zone ID"
  value       = aws_lb.main.zone_id
}

output "s3_bucket_name" {
  description = "S3 artifacts bucket name"
  value       = aws_s3_bucket.artifacts.id
}

output "ecs_security_group_id" {
  description = "ECS security group ID"
  value       = aws_security_group.ecs.id
}

output "ecs_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  value       = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "ecs_cluster_vpc_security_group_id" {
  description = "ECS cluster VPC security group ID"
  value       = aws_vpc.main.default_security_group_id
}

output "log_group_name" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "secrets" {
  description = "Secrets that need to be populated manually"
  value = {
    slack_bot_token      = aws_secretsmanager_secret.slack_bot_token.name
    slack_signing_secret = aws_secretsmanager_secret.slack_signing_secret.name
    gcp_sa_key           = aws_secretsmanager_secret.gcp_sa_key.name
    qdrant_api_key       = aws_secretsmanager_secret.qdrant_api_key.name
    vertex_api_key       = aws_secretsmanager_secret.vertex_api_key.name
  }
}
