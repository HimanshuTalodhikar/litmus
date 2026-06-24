# ECS Task Definition — Backend Service

data "aws_secretsmanager_secret_version" "db_password" {
  secret_id = "product-copilot/db-password"
}

data "aws_secretsmanager_secret_version" "gcp_sa_key" {
  secret_id = "product-copilot/gcp-sa-key"
}

data "aws_secretsmanager_secret_version" "qdrant_api_key" {
  secret_id = "product-copilot/qdrant-api-key"
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "product-copilot-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn           = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "product-copilot-backend"
    image     = "${aws_ecr_repository.backend.repository_url}:latest"
    essential = true
    portMappings = [{ containerPort = 8080 }]

    environment = [
      { name = "ENVIRONMENT", value = var.project_env },
      { name = "AWS_REGION", value = var.aws_region },
    ]

    secrets = [
      { name = "DB_PASSWORD",     valueFrom = data.aws_secretsmanager_secret_version.db_password.arn },
      { name = "GCP_SA_KEY_JSON", valueFrom = data.aws_secretsmanager_secret_version.gcp_sa_key.arn },
      { name = "QDRANT_API_KEY",  valueFrom = data.aws_secretsmanager_secret_version.qdrant_api_key.arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs/backend"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_service" "backend" {
  name            = "product-copilot-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "product-copilot-backend"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.http]

  enable_execute_command = true
}
