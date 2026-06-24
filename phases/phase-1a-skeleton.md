# Phase 1A — Project Bootstrap (Days 6–9)

**Goal:** A running FastAPI application on ECS Fargate that can receive HTTP requests, with all dependencies wired up and a basic health check endpoint.

**Time estimate:** 3–4 days

---

## What This Produces

A working FastAPI app running on ECS Fargate behind an ALB. No Slack bot yet, no RAG yet. Just: build → push → run → verify it works.

---

## Deliverables

### 1. Project Structure

```
product-copilot/
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py              # Settings from env vars
│   ├── __init__.py
│   ├── db/
│   │   ├── session.py         # asyncpg PostgreSQL
│   │   ├── redis_client.py    # async Redis
│   │   └── qdrant_client.py  # Qdrant Cloud
│   └── routers/
│       └── health.py          # /health endpoint
├── Dockerfile                 # Multi-stage build
├── docker-compose.yml         # Local dev (Postgres + Redis + Qdrant + app)
├── requirements.txt           # All Python dependencies
├── .env.example              # Env var template
├── Makefile                  # Build/run shortcuts
├── .gitignore
├── tests/
│   ├── conftest.py           # Shared pytest fixtures
│   └── test_health.py        # Basic health check test
└── infra/terraform/           # All AWS infrastructure
```

### 2. Configuration (`backend/config.py`)

```python
# backend/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    app_name: str = "product-copilot"
    environment: str = "dev"
    log_level: str = "INFO"

    # AWS
    aws_region: str = "us-east-1"
    ecs_cluster_name: str = "product-copilot-dev"

    # CodeMax LLM
    codermax_api_key: str = ""
    codermax_base_url: str = "https://api.codemax.pro"
    codermax_model: str = "claude-sonnet-4-6"

    # Qdrant Cloud
    qdrant_url: str = ""
    qdrant_api_key: str = ""

    # Slack (filled in Phase 1C)
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # RDS
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "productcopilot"
    db_user: str = "copilot_user"
    db_password: str = ""

    # Redis
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_use_ssl: bool = True

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"
        extra = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 3. FastAPI App (`backend/main.py`)

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
from app.config import get_settings
from app.routers import health

settings = get_settings()
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)

@app.get("/")
async def root():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}

logger.info("product_copilot_started", env=settings.environment)
```

### 4. Health Router (`backend/routers/health.py`)

```python
# backend/routers/health.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])

class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    qdrant: str

@router.get("", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    # Check DB
    try:
        await db.execute("SELECT 1")
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    # Check Redis (imported from app.db.redis_client)
    from app.db.redis_client import get_redis
    try:
        redis = await get_redis()
        await redis.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    # Check Qdrant
    try:
        from app.db.qdrant_client import get_qdrant
        qdrant = get_qdrant()
        collections = qdrant.get_collections()
        qdrant_status = "ok"
    except Exception as e:
        qdrant_status = f"error: {e}"

    overall = "ok" if all(s == "ok" for s in [db_status, redis_status, qdrant_status]) else "degraded"
    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        qdrant=qdrant_status,
    )
```

### 5. Database Session (`backend/db/session.py`)

```python
# backend/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with async_session_maker() as session:
        yield session
```

### 6. Redis Client (`backend/db/redis_client.py`)

```python
# backend/db/redis_client.py
import redis.asyncio as redis
from app.config import get_settings

_settings = None

def get_redis_client() -> redis.Redis:
    global _settings
    if _settings is None:
        _settings = get_settings()
    return redis.Redis(
        host=_settings.redis_host,
        port=6379,
        password=_settings.redis_password,
        ssl=True,
        decode_responses=True,
    )

async def get_redis():
    return get_redis_client()
```

### 7. Qdrant Client (`backend/db/qdrant_client.py`)

```python
# backend/db/qdrant_client.py
from qdrant_client import QdrantClient
from app.config import get_settings

_qdrant = None

def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        settings = get_settings()
        _qdrant = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )
    return _qdrant
```

### 8. Dockerfile

```dockerfile
# Dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# --- Production stage ---
FROM python:3.12-slim

WORKDIR /app

# Install AWS CLI for Secrets Manager (or use boto3 directly)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY app/ ./app/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 9. docker-compose.yml (Local Dev)

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=productcopilot
      - DB_USER=copilot
      - DB_PASSWORD=password
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=password
      - QDRANT_URL=http://qdrant:6333
      - QDRANT_API_KEY=dummy-key
      - CODERMAX_API_KEY=sk-cm-your-key
      - CODERMAX_BASE_URL=https://api.codemax.pro
      - CODERMAX_MODEL=claude-sonnet-4-6
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: copilot
      POSTGRES_PASSWORD: password
      POSTGRES_DB: productcopilot
    ports:
      - "5432:5432"
    health_check:
      test: ["CMD-SHELL", "pg_isready -U copilot"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass password
    ports:
      - "6379:6379"
    health_check:
      test: ["CMD", "redis-cli", "-a", "password", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
```

### 10. Requirements.txt

```
# requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic-settings>=2.5.0
structlog>=24.4.0

# Database
sqlalchemy[asyncio]>=2.0.35
asyncpg>=0.30.0
redis[hiredis]>=5.1.0

# LLM
anthropic>=0.40.0

# Vector DB
qdrant-client>=1.12.0

# AWS
boto3>=1.35.0

# Slack
slack-sdk>=3.33.0
slack-bolt>=1.20.0

# Utilities
httpx>=0.27.2
python-dotenv>=1.0.1
pydantic>=2.9.0

# Testing
pytest>=8.3.0
pytest-asyncio>=0.24.0
pytest-cov>=5.0.0
```

### 11. ECS Task Definition (Terraform)

```hcl
# infra/terraform/ecs_task_definition.tf

data "aws_secretsmanager_secret_version" "codermax_api_key" {
  secret_id = "product-copilot/codermax-api-key"
}

data "aws_secretsmanager_secret_version" "qdrant_api_key" {
  secret_id = "product-copilot/qdrant-api-key"
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "product-copilot-backend"
  network_mode            = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                     = "512"     # 0.5 vCPU
  memory                  = "1024"    # 1 GB
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
      { name = "CODERMAX_API_KEY", valueFrom = data.aws_secretsmanager_secret_version.codermax_api_key.arn },
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
    security_groups   = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "product-copilot-backend"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.http]
}
```

### 12. ECR Repository

```hcl
# infra/terraform/ecr.tf
resource "aws_ecr_repository" "backend" {
  name = "product-copilot-backend"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}
```

### 13. Makefile

```makefile
# Makefile
.PHONY: build push deploy local test clean

REGION      := us-east-1
ECR_REPO    := $(shell aws ecr describe-repositories --repository-names product-copilot-backend --region $(REGION) --query 'repositories[0].repositoryUri' --output text)
IMAGE_TAG   := $(shell git rev-parse --short HEAD)

build:
	docker build -t product-copilot-backend:latest .

local:
	docker compose up --build

push: build
	docker tag product-copilot-backend:latest $(ECR_REPO):$(IMAGE_TAG)
	docker tag product-copilot-backend:latest $(ECR_REPO):latest
	docker push $(ECR_REPO):$(IMAGE_TAG)
	docker push $(ECR_REPO):latest

deploy: push
	aws ecs update-service \
		--cluster product-copilot-dev \
		--service product-copilot-backend \
		--force-new-deployment \
		--region $(REGION)

test:
	pytest tests/ -v

clean:
	docker compose down -v --remove-orphans
```

---

## Verification Steps

After Phase 1A, you must verify:

1. **Local:** `docker compose up` → app runs on `localhost:8080` → `/health` returns `{"status": "ok"}`
2. **Remote:** ALB DNS name → `GET /health` returns same JSON
3. **Database:** Health check shows `"database": "ok"`
4. **Redis:** Health check shows `"redis": "ok"`
5. **Qdrant:** Health check shows `"qdrant": "ok"` (or local dev uses embedded Qdrant)

---

## Common Issues to Watch For

| Issue | Fix |
|---|---|
| ECS task can't reach Secrets Manager | Ensure VPC has NAT Gateway + internet access, or use VPC endpoints for Secrets Manager |
| Health check fails on ECS | Add `startPeriod: 60` — DB takes time to initialize |
| Redis connection refused | Check ElastiCache is in same VPC security group |
| Qdrant connection timeout | Qdrant Cloud URL must be HTTPS and accessible from VPC (add NAT Gateway) |

---

## What to Commit to Git

```
.gitignore           # .env, __pycache__, .pytest_cache, *.pyc
requirements.txt
Dockerfile
docker-compose.yml
Makefile
app/
  main.py
  config.py
  routers/health.py
  db/
    session.py
    redis_client.py
    qdrant_client.py
infra/terraform/
  *.tf (all terraform files)
tests/
  conftest.py
  test_health.py
.env.example
```
