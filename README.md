# Product Copilot — Architecture & Implementation Plan

An AI-powered Slack-based Product Copilot that answers product questions, deduplicates feature requests, generates implementation plans, and syncs with Jira.

**Cloud:** AWS (primary) + GCP Vertex AI (LLM via ADK) + Qdrant Cloud (vector DB)

---

## What It Does

```
User in Slack
    │
    ├── "How do I reset my password?" ────────────▶ RAG → Qdrant → Gemini → Answer + Citations
    │
    ├── "Add CSV export to analytics" ────────────▶ ADK Feature Intake Agent
    │                                                ├── Dedup check → Match found → Show existing FR
    │                                                └── New → Enrich → Score → Jira ticket
    │
    ├── "/product plan FR-234" ───────────────────▶ ADK Plan Gen Agent → Multi-phase plan
    │
    └── "What's the status of FR-200?" ───────────▶ Jira Sync → Status update
```

---

## Hybrid Cloud Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  AWS (Your Org Account)                                                │
│                                                                       │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐     │
│  │ Slack       │    │  ECS Fargate                             │     │
│  │ (Slack API) │────▶  │  • Slack Bolt handlers                  │     │
│  └─────────────┘    │  • Google ADK agents                      │     │
│                      │  • FastAPI backend                       │     │
│                      │  • Async workers (Redis/SQS)             │     │
│                      └──────────────┬───────────────────────────┘     │
│                                     │                               │
│         ┌──────────────────────────┼──────────────────────────┐    │
│         │                          │                              │    │
│  ┌──────▼──────┐  ┌──────────────▼───────┐  ┌──────────────▼─┐  │
│  │ RDS          │  │ ElastiCache Redis    │  │ S3             │  │
│  │ PostgreSQL   │  │ (sessions, cache)    │  │ (artifacts)    │  │
│  └──────────────┘  └─────────────────────┘  └────────────────┘  │
│                                       │                             │
│         ┌─────────────────────────────┼────────────────────────┐   │
│         │ EventBridge                 │ SNS / SQS              │   │
│         │ (scheduled jobs, webhooks)   │ (async processing)     │   │
│         └───────────────────────────────────────────────────────┘   │
│                                                                        │
│         ┌────────────────────────────────────────────────────────┐   │
│         │ CloudWatch (Logs + Metrics + Alarms)                  │   │
│         └────────────────────────────────────────────────────────┘   │
│                                                                        │
│         ┌────────────────────────────────────────────────────────┐   │
│         │ Secrets Manager (tokens, API keys, credentials)       │   │
│         └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │ HTTPS (TLS)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GCP (Minimal — LLM only)                                           │
│  • Vertex AI ── Gemini 2.5 Flash / Pro (via ADK)                  │
│  • text-embedding-004                                               │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Qdrant Cloud (Managed Vector DB)                                   │
│  • product_copilot_knowledge collection                             │
│  • product_copilot_feature_requests collection                      │
│  • product_copilot_jira_shipped collection (Phase 3+)              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Service | Notes |
|---|---|---|
| **Agent framework** | Google ADK | Runs on AWS, calls GCP Vertex AI |
| **LLM** | Vertex AI | Gemini 2.5 Flash (QA) / Pro (planning) |
| **Embeddings** | Vertex AI | text-embedding-004 (768-dim) |
| **Vector DB** | Qdrant Cloud | Managed, TLS, API-key auth |
| **Compute** | AWS ECS Fargate | Serverless containers |
| **Database** | AWS RDS PostgreSQL 16 | Multi-AZ, automated backups |
| **Cache** | AWS ElastiCache Redis | Sessions, conversation context |
| **Object storage** | AWS S3 | Artifacts, prompt configs |
| **Secrets** | AWS Secrets Manager | All credentials |
| **Logging** | AWS CloudWatch Logs | Structured JSON |
| **Monitoring** | AWS CloudWatch Metrics | Latency, errors, custom |
| **Events** | AWS EventBridge | Scheduled jobs, triggers |
| **Queues** | AWS SNS / SQS | Async processing |
| **IaC** | Terraform | All AWS infrastructure |

---

## Phases

| Phase | Name | Timeline | Goal |
|---|---|---|---|
| [Phase 0](phases/phase-0-gcp-setup.md) | Infrastructure Setup | Days 1–5 | AWS + GCP + Qdrant Cloud provisioned |
| [Phase 1A](phases/phase-1a-skeleton.md) | Project Bootstrap | Days 6–9 | FastAPI on ECS, DB/Redis connected |
| [Phase 1B](phases/phase-1b-adk-setup.md) | ADK Setup | Days 10–14 | ADK running, Gemini calls working |
| [Phase 1C](phases/phase-1c-slack-integration.md) | Slack Integration | Days 15–22 | Bot responds in real time |
| [Phase 1D](phases/phase-1d-rag-pipeline.md) | RAG Pipeline | Days 23–32 | Bot answers from real documents |
| [Phase 2](phases/phase-2-evolved.md) | Feature Request Lifecycle | Weeks 9–20 | FRs, dedup, Jira, feedback |
| [Phase 3](phases/phase-3-mature.md) | Production Hardened | Weeks 21–36 | Plans, curator, A/B testing, dashboard |
| [Phase 4](phases/phase-4-scale-enterprise.md) | Scale & Enterprise | Weeks 37–48 | Multi-workspace, HA, SSO, audit |
| [Phase 5](phases/phase-5-advanced.md) | Advanced | Weeks 49–60 | Voice, plugins, public API |

---

## Key Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent framework | Google ADK | Native tool-calling, session management |
| LLM | Gemini 2.5 (Vertex AI) | ADK-native, cost-efficient |
| Vector DB | Qdrant Cloud | No ops, managed, free tier available |
| Agent pattern | ADK Root Agent + Sub-Agents | Supervisor routing, ADK-native |
| Dedup threshold | 0.92 auto / 0.65 human | Balances noise vs misses |
| RAG | Hybrid (vector + BM25) + RRF | Best answer quality |
| Priority | Modified RICE | Intelligible to PMs |
| Compute | ECS Fargate | Serverless containers on AWS |
| DB | RDS PostgreSQL | Your org's AWS, no data residency issues |
| Event bus | EventBridge + SNS/SQS | AWS-native, serverless |
| Infrastructure | Terraform | All AWS resources as code |

---

## Getting Started: Phase 0

Start with [Phase 0](phases/phase-0-gcp-setup.md) — provisioning takes 1–2 days.

Then work through Phase 1 sub-phases in order:
1. **1A** → FastAPI app running on ECS
2. **1B** → ADK calling Gemini
3. **1C** → Slack bot responds in real time
4. **1D** → RAG working with real documents

Ship Phase 1 before adding any Phase 2 features.
