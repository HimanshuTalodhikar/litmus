# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cloud Architecture

This is a greenfield project — Phase 1A (FastAPI skeleton) has been built. All implementation plans live in `phases/*.md`.

**Hybrid cloud model:**
- **AWS (primary):** ECS Fargate, RDS PostgreSQL, ElastiCache Redis, S3, Secrets Manager, EventBridge, CloudWatch
- **LLM:** CodeMax (Anthropic-compatible API at `https://api.codemax.pro/v1/messages`) — Claude Sonnet/Opus
- **Qdrant Cloud:** Managed vector database (not self-hosted)

LLM calls go through CodeMax, not GCP. All other infrastructure runs on the org's AWS account.

## Project Structure

```
phases/
├── phase-0-gcp-setup.md      # Infrastructure provisioning (Day 1)
├── phase-1a-skeleton.md      # FastAPI app on ECS (Days 6–9)
├── phase-1b-adk-setup.md    # Google ADK + Gemini (Days 10–14)
├── phase-1c-slack-integration.md  # Slack bot (Days 15–22)
├── phase-1d-rag-pipeline.md # RAG + Qdrant (Days 23–32)
├── phase-2-evolved.md        # Feature requests + Jira
├── phase-3-mature.md        # Plan generation + curator
├── phase-4-scale-enterprise.md  # Multi-workspace + HA
└── phase-5-advanced.md      # Voice + plugins + public API
```

Work through phases in order. Ship Phase 1 before Phase 2.

## Key Dependencies

- **CodeMax LLM:** Anthropic SDK calls CodeMax `/v1/messages` API. Set `CODERMAX_API_KEY` in `.env`. Never commit the key.
- **Qdrant Cloud:** Vector DB accessed via REST API with API key. No infra to manage.
- **Slack:** Uses Bolt SDK (Python). Bot tokens go in AWS Secrets Manager, not in code.

## Before Writing Code

When implementing any phase file, read the corresponding `phases/phase-X*.md` first — it contains the full implementation plan including exact file paths, Terraform resources, code patterns, and verification steps.

## Running Locally

```bash
docker compose up --build
curl http://localhost:8080/health
```

Note: `docker-compose.yml` uses `healthcheck` (one word) as the key name — not `health_check`.

## Project Code Structure

```
litmus/
├── app/                        # FastAPI application (Phase 1A)
│   ├── main.py                 # App entry point
│   ├── config.py               # Settings from env vars
│   ├── db/
│   │   ├── session.py          # asyncpg PostgreSQL
│   │   ├── redis_client.py     # async Redis
│   │   └── qdrant_client.py   # Qdrant Cloud
│   └── routers/
│       └── health.py           # GET /health
├── tests/
│   └── test_health.py
├── Dockerfile
├── docker-compose.yml           # Local dev (Postgres + Redis + Qdrant)
├── requirements.txt
├── .env.example
├── Makefile
└── infra/terraform/            # All AWS infrastructure
```

## Docker Compose Note

`docker-compose.yml` uses `healthcheck` (one word) — NOT `health_check` (underscore). The Compose file format requires the camelCase key.

## Cloud Provider Context

- Use AWS SDK (`boto3`) for all AWS resource access — ECS, RDS, Secrets Manager, S3, EventBridge
- Use `anthropic` SDK for LLM calls via CodeMax
- Use `qdrant-client` for vector DB operations
- Use `slack-bolt` for Slack integration
