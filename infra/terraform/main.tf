# ============================================================
# Phase 0: Infrastructure Setup
# Product Copilot — AWS Infrastructure (Terraform)
#
# Resources created:
#   - VPC with public + private subnets
#   - NAT Gateway + Internet Gateway
#   - RDS PostgreSQL (in private subnets)
#   - ElastiCache Redis (in private subnets)
#   - ECS Fargate cluster
#   - Application Load Balancer
#   - IAM roles for ECS tasks
#   - S3 bucket
#   - Secrets Manager (secrets created; values filled in separately)
#   - CloudWatch Log Group
# ============================================================

# ============================================================
# VPC
# ============================================================
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "product-copilot-vpc"
  }
}

# Private subnet — AZ A
resource "aws_subnet" "private_a" {
  cidr_block              = "10.0.1.0/24"
  vpc_id                  = aws_vpc.main.id
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = {
    Name = "product-copilot-private-a"
  }
}

# Private subnet — AZ B
resource "aws_subnet" "private_b" {
  cidr_block              = "10.0.2.0/24"
  vpc_id                  = aws_vpc.main.id
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = false

  tags = {
    Name = "product-copilot-private-b"
  }
}

# Public subnet — AZ A (for ALB + NAT Gateway)
resource "aws_subnet" "public_a" {
  cidr_block              = "10.0.0.0/24"
  vpc_id                  = aws_vpc.main.id
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = {
    Name = "product-copilot-public-a"
  }
}

# Public subnet — AZ B (required for ALB multi-AZ)
resource "aws_subnet" "public_b" {
  cidr_block              = "10.0.3.0/24"
  vpc_id                  = aws_vpc.main.id
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = true

  tags = {
    Name = "product-copilot-public-b"
  }
}

# Elastic IP for NAT Gateway
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "product-copilot-nat-eip"
  }
}

# NAT Gateway
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_a.id

  tags = {
    Name = "product-copilot-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "product-copilot-igw"
  }
}

# Route table for private subnets (via NAT Gateway)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "product-copilot-private-rt"
  }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# Route table for public subnet (via Internet Gateway)
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "product-copilot-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# ============================================================
# Security Groups
# ============================================================

# ECS Security Group — tasks live here
resource "aws_security_group" "ecs" {
  name        = "product-copilot-ecs-sg"
  description = "Security group for ECS Fargate tasks"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "product-copilot-ecs-sg"
  }
}

# ALB Security Group
resource "aws_security_group" "alb" {
  name        = "product-copilot-alb-sg"
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "product-copilot-alb-sg"
  }
}

# RDS Security Group
resource "aws_security_group" "db" {
  name        = "product-copilot-db-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "product-copilot-db-sg"
  }
}

# ElastiCache Security Group
resource "aws_security_group" "redis" {
  name        = "product-copilot-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "product-copilot-redis-sg"
  }
}

# ============================================================
# RDS PostgreSQL
# ============================================================
resource "aws_db_subnet_group" "main" {
  name       = "product-copilot-db-subnet"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "product-copilot-db-subnet"
  }
}

resource "aws_db_instance" "postgres" {
  identifier             = "product-copilot-db"
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  max_allocated_storage  = var.db_max_allocated_storage
  db_name                = "productcopilot"
  username               = "copilot_user"
  password               = aws_secretsmanager_secret_version.db_password.secret_string
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  skip_final_snapshot    = true
  publicly_accessible    = false

  backup_retention_period = 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"
  deletion_protection     = false

  tags = {
    Name = "product-copilot-db"
  }
}

# ============================================================
# ElastiCache Redis
# ============================================================
resource "aws_elasticache_subnet_group" "main" {
  name       = "product-copilot-redis-subnet"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id         = "product-copilot-redis"
  engine             = "redis"
  engine_version     = "7.1"
  node_type          = var.cache_instance_class
  num_cache_nodes    = 1
  port               = 6379
  security_group_ids = [aws_security_group.redis.id]
  subnet_group_name  = aws_elasticache_subnet_group.main.name

  tags = {
    Name = "product-copilot-redis"
  }
}

# ============================================================
# S3 Bucket
# ============================================================
resource "aws_s3_bucket" "artifacts" {
  bucket = "product-copilot-artifacts-us-east-1-dev-1782213910"

  tags = {
    Name = "product-copilot-artifacts"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ============================================================
# Secrets Manager
# ====================================

# DB Password — auto-generated
resource "aws_secretsmanager_secret" "db_password" {
  name        = "product-copilot/db-password"
  description = "PostgreSQL password for Product Copilot"

  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db_password.result
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

# Slack Bot Token
resource "aws_secretsmanager_secret" "slack_bot_token" {
  name        = "product-copilot/slack-bot-token"
  description = "Slack Bot User OAuth Token"

  recovery_window_in_days = 0
}

# Slack Signing Secret
resource "aws_secretsmanager_secret" "slack_signing_secret" {
  name        = "product-copilot/slack-signing-secret"
  description = "Slack Signing Secret for webhook verification"

  recovery_window_in_days = 0
}

# GCP Service Account JSON Key
resource "aws_secretsmanager_secret" "gcp_sa_key" {
  name        = "product-copilot/gcp-sa-key"
  description = "GCP Service Account JSON key for Vertex AI access"

  recovery_window_in_days = 0
}

# Qdrant Cloud API Key
resource "aws_secretsmanager_secret" "qdrant_api_key" {
  name        = "product-copilot/qdrant-api-key"
  description = "Qdrant Cloud API key for vector database access"

  recovery_window_in_days = 0
}

# Vertex AI API Key
resource "aws_secretsmanager_secret" "vertex_api_key" {
  name        = "product-copilot/vertex-api-key"
  description = "GCP Vertex AI API key (alternative to service account)"

  recovery_window_in_days = 0
}

# ============================================================
# IAM Roles
# ============================================================

# ECS Task Execution Role
resource "aws_iam_role" "ecs_execution_role" {
  name = "product-copilot-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "product-copilot-ecs-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
}

resource "aws_iam_role_policy_attachment" "ecs_execution_ecr" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# ECS Task Role
resource "aws_iam_role" "ecs_task_role" {
  name = "product-copilot-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "product-copilot-ecs-task-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_s3" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

# ============================================================
# ECS Cluster
# ============================================================
resource "aws_ecs_cluster" "main" {
  name = "product-copilot-${var.project_env}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "product-copilot-ecs-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# ============================================================
# Application Load Balancer
# ============================================================
resource "aws_lb" "main" {
  name               = "product-copilot-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  enable_deletion_protection = false

  tags = {
    Name = "product-copilot-alb"
  }
}

resource "aws_lb_target_group" "backend" {
  name     = "product-copilot-backend-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "product-copilot-backend-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

# ============================================================
# CloudWatch Log Group
# ============================================================
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/product-copilot-${var.project_env}"
  retention_in_days = 7

  tags = {
    Name = "product-copilot-ecs-logs"
  }
}
