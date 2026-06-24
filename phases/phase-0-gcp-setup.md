# Phase 0 — Infrastructure Setup (Days 1–5)

**Goal:** Get CodeMax API key, Qdrant Cloud cluster, and AWS infrastructure provisioned before writing any application code.

---

## Scope

This phase produces zero application code. It produces:
- CodeMax API key for LLM calls
- Qdrant Cloud cluster (free tier or paid) with API key
- AWS account: VPC, ECS cluster, RDS PostgreSQL, ElastiCache Redis, S3 bucket, Secrets Manager, IAM roles

---

## Deliverables

### 1. CodeMax Setup

**Steps:**

1. **Get a CodeMax API key**
   - Sign up at https://www.codemax.pro
   - Copy your API key (format: `sk-cm-...`)
   - Store it in AWS Secrets Manager

2. **Test the API**
   ```bash
   curl https://api.codemax.pro/v1/models \
     -H "Authorization: Bearer sk-cm-YOUR-KEY"
   ```
   You should see `claude-opus-4-8`, `claude-sonnet-4-6`, and `claude-haiku-4-5` models.

3. **Available models:**
   - `claude-opus-4-8` — most capable, higher cost
   - `claude-sonnet-4-6` — balanced (default)
   - `claude-haiku-4-5` — fastest, lowest cost

4. **API endpoint:** `POST https://api.codemax.pro/v1/messages` (Anthropic Messages format)
   - Also supports: `POST https://api.codemax.pro/v1/chat/completions` (OpenAI format)

### 2. Qdrant Cloud Setup

**Steps:**

1. **Create Qdrant Cloud account**
   - Go to https://cloud.qdrant.io
   - Sign up (free tier: 1 cluster, 1GB RAM)
   - Create a cluster: name it `product-copilot`, region `us-east-1` (or closest to your AWS region)

2. **Get API key**
   - Copy the API key from the Qdrant Cloud dashboard
   - Store it in AWS Secrets Manager (next AWS step)

3. **Test connection**
   ```python
   pip install qdrant-client
   python -c "
   from qdrant_client import QdrantClient
   client = QdrantClient(
       url='https://YOUR_CLUSTER.qdrant.io',
       api_key='YOUR_API_KEY'
   )
   print(client.get_collections())
   "
   ```

### 3. AWS Infrastructure (Terraform)

**Directory:** `infra/terraform/`

**Files to create:**

#### `infra/terraform/providers.tf`
```hcl
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source  = "hashicorp/aws"  version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
}
```

#### `infra/terraform/variables.tf`
```hcl
variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_env" {
  description = "Environment: dev, staging, or prod"
  type        = string
  default     = "dev"
}
```

#### `infra/terraform/main.tf` (VPC + ECS + RDS + ElastiCache + S3 + Secrets)
```hcl
# ============================================================
# VPC
# ============================================================
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "product-copilot-vpc" }
}

resource "aws_subnet" "private_a" {
  cidr_block        = "10.0.1.0/24"
  vpc_id            = aws_vpc.main.id
  availability_zone = "${var.aws_region}a"
  tags = { Name = "product-copilot-private-a" }
}

resource "aws_subnet" "private_b" {
  cidr_block        = "10.0.2.0/24"
  vpc_id            = aws_vpc.main.id
  availability_zone = "${var.aws_region}b"
  tags = { Name = "product-copilot-private-b" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"
}

resource "aws_subnet" "public" {
  cidr_block = "10.0.0.0/24"
  vpc_id     = aws_vpc.main.id
  tags = { Name = "product-copilot-public" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
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

# ============================================================
# RDS PostgreSQL
# ============================================================
resource "aws_db_subnet_group" "main" {
  name       = "product-copilot-db-subnet"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_db_instance" "postgres" {
  identifier           = "product-copilot-db"
  engine              = "postgres"
  engine_version      = "16.3"
  instance_class      = "db.t4g.micro"     # Free tier / dev only
  allocated_storage   = 20                   # GB
  max_allocated_storage = 100

  db_name  = "productcopilot"
  username = "copilot_user"
  password = aws_secretsmanager_secret_version.db_password.secret_string

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  skip_final_snapshot    = true
  publicly_accessible    = false

  backup_retention_period = 1
  deletion_protection     = false  # true in prod
}

resource "aws_security_group" "db" {
  name        = "product-copilot-db-sg"
  description = "Allow PostgreSQL from ECS tasks"
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
}

# ============================================================
# ElastiCache Redis
# ============================================================
resource "aws_elasticache_subnet_group" "main" {
  name       = "product-copilot-redis-subnet"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "product-copilot-redis"
  engine              = "redis"
  engine_version      = "7.1"
  node_type           = "cache.t4g.micro"    # Free tier / dev
  num_cache_nodes     = 1
  port               = 6379
  security_group_ids = [aws_security_group.redis.id]
  subnet_group_name  = aws_elasticache_subnet_group.main.name
}

resource "aws_security_group" "redis" {
  name        = "product-copilot-redis-sg"
  description = "Allow Redis from ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}

# ============================================================
# S3 Bucket
# ============================================================
resource "aws_s3_bucket" "artifacts" {
  bucket = "product-copilot-artifacts-${var.aws_region}"
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
# ============================================================
# DB Password (auto-generated)
resource "aws_secretsmanager_secret" "db_password" {
  name = "product-copilot/db-password"
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db_password.result
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

# Slack Bot Token
resource "aws_secretsmanager_secret" "slack_bot_token" {
  name = "product-copilot/slack-bot-token"
}

# Slack Signing Secret
resource "aws_secretsmanager_secret" "slack_signing_secret" {
  name = "product-copilot/slack-signing-secret"
}

# Qdrant Cloud API Key
resource "aws_secretsmanager_secret" "qdrant_api_key" {
  name = "product-copilot/qdrant-api-key"
}

# CodeMax API Key
resource "aws_secretsmanager_secret" "codermax_api_key" {
  name = "product-copilot/codermax-api-key"
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
# IAM Roles (ECS Task Execution + Task)
# ============================================================
resource "aws_iam_role" "ecs_execution_role" {
  name = "product-copilot-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
}

resource "aws_iam_role_policy_attachment" "ecs_execution_ecr" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "product-copilot-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_s3" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

# ============================================================
# Security Groups
# ============================================================
resource "aws_security_group" "ecs" {
  name        = "product-copilot-ecs-sg"
  description = "ECS tasks security group"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
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
  subnets            = [aws_subnet.public.id]

  enable_deletion_protection = false  # true in prod
}

resource "aws_security_group" "alb" {
  name        = "product-copilot-alb-sg"
  description = "Allow HTTP/HTTPS from internet"
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
# CloudWatch
# ============================================================
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/product-copilot-${var.project_env}"
  retention_in_days = 7
}
```

---

## Secrets to Fill In

After running `terraform apply`, fill in these secrets manually (or in your CI/CD pipeline):

| Secret Name | Where to Get It |
|---|---|
| `product-copilot/slack-bot-token` | Slack App settings → Bot User OAuth Token |
| `product-copilot/slack-signing-secret` | Slack App settings → Signing Secret |
| `product-copilot/codermax-api-key` | CodeMax dashboard at https://www.codemax.pro |
| `product-copilot/qdrant-api-key` | Qdrant Cloud dashboard → API Key |

---

## Verification Checklist

Before moving to Phase 1A, verify:

- [ ] CodeMax API key works (`curl` to `/v1/models` returns model list)
- [ ] Qdrant Cloud cluster accessible via Python client
- [ ] `terraform apply` completes without error
- [ ] RDS PostgreSQL accessible from a test EC2 instance in the VPC
- [ ] ElastiCache Redis accessible from same test instance
- [ ] All secrets stored in Secrets Manager
- [ ] ECS cluster visible in AWS Console
- [ ] ALB DNS name reachable from internet

---

## Time Estimate

- CodeMax setup: 5 minutes
- Qdrant Cloud: 15 minutes
- Terraform: 2–3 hours (first run)
- Total: **~3 hours** (can be done in 1 day if pacing yourself)
