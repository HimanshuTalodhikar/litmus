# Phase 1 — MVP: Working Slack Bot (Weeks 1–8)

**Goal:** A functioning Slack bot that answers product questions from a small, manually curated knowledge corpus.

**Cloud:** Google Cloud Platform (GCP)
**Framework:** Google Agent Development Kit (ADK)

---

## Scope

### In Scope

- Slack Bolt app with DM and `/product ask` slash command
- Google ADK agent orchestration (Root Agent = Router, Sub-Agent = Product Q&A)
- Manual ingestion of 3–5 critical documents into Vertex AI Vector Search
- RAG pipeline: chunk → embed → store → retrieve → synthesize → cite
- Ephemeral acknowledgment → async response pattern (handles Slack's 3s timeout)
- Basic observability: Cloud Logging, Cloud Monitoring
- Single Slack workspace support

### Out of Scope (for Phase 1)

- Feature request capture
- Jira integration
- Deduplication detection
- Plan generation
- Feedback loop
- Automated source connectors
- Multi-workspace support

---

## Deliverables

### 1. GCP Infrastructure Setup

**Infrastructure Components:**

| Component | GCP Service | Details |
|---|---|---|
| Compute | Cloud Run | Serverless, scales to zero, Python runtime |
| Database | Cloud SQL (PostgreSQL 16) | Private IP, automated backups |
| Cache / Session | Memorystore for Redis | Version 7, Standard tier |
| Vector DB | Vertex AI Vector Search | Ann index, 1024 dimensions |
| Embeddings | Vertex AI (gemini-embedding-004) | 3072-dim, reduced to 1024d for storage |
| Object storage | Cloud Storage | Document blobs, ingestion artifacts |
| Secrets | Secret Manager | API keys, bot tokens, DB credentials |
| Logging | Cloud Logging | Structured JSON logs, all services |
| Monitoring | Cloud Monitoring + Cloud Trace | Latency, error rates, traces |
| Networking | VPC + Private Service Connect | Secure, no public DB exposure |

**IaC:** Terraform (stored in `infra/terraform/`)

**GCP Project Structure:**
```
project: product-copilot-{env}
├── Cloud Run: product-copilot-backend
├── Cloud SQL: product-copilot-db (postgres)
├── Memorystore: product-copilot-redis
├── Vertex AI: product-copilot-index (Vector Search)
├── Secret Manager: copilot-secrets
├── Cloud Storage: product-copilot-artifacts
└── VPC: product-copilot-vpc
```

### 2. Google ADK Agent Architecture

**File:** `backend/agents/root_agent.py`

Google ADK uses a session-based agent model. The Root Agent acts as the supervisor.

```python
# backend/agents/root_agent.py
from google.adk.agents import Agent
from google.adk.tools import Tool
from .sub_agents.product_qa_agent import product_qa_agent
from .sub_agents.intent_classifier import intent_classifier

root_agent = Agent(
    name="product_copilot_root",
    model="gemini-2.5-flash",          # Vertex AI model
    description="Routes user messages to the correct specialized agent",
    instruction="""
    You are the Product Copilot router. For every user message:
    1. Classify the intent: product_q | feature_req | status_check | plan_gen | general
    2. Based on intent, delegate to the appropriate sub-agent
    3. If confidence is low, ask the user for clarification

    Available sub-agents:
    - product_qa_agent: for product knowledge questions
    - feature_intake_agent: for feature requests (Phase 2)
    - plan_gen_agent: for implementation plan requests (Phase 3)

    Respond conversationally and helpfully.
    """,
    sub_agents=[
        product_qa_agent,  # Phase 1
        # feature_intake_agent,  # Phase 2
        # plan_gen_agent,        # Phase 3
    ],
    tools=[
        retrieve_product_knowledge,
        get_conversation_context,
    ]
)
```

**Session Management:**
```python
# ADK sessions are stored in Memorystore (Redis) via custom session service
# Session ID = Slack thread_ts
# Each session stores: turns, current intent, workspace_id

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

runner = Runner(
    app_name="product-copilot",
    agent=root_agent,
    session_service=redis_session_service,  # Custom, backed by Memorystore
)
```

**ADK Tool Definition:**
```python
# backend/agents/tools/retrieval_tools.py
from google.adk.tools import Tool

retrieve_product_knowledge = Tool(
    name="retrieve_product_knowledge",
    description="Search the product knowledge base for information relevant to the user's question. "
                "Returns documents with citations.",
    parameters={
        "query": {"type": "string", "description": "The user's question"},
        "top_k": {"type": "integer", "description": "Number of results", "default": 5}
    }
)

async def retrieve_product_knowledge_impl(query: str, top_k: int = 5) -> dict:
    # 1. Query Vertex AI Vector Search (top_k * 2 candidates)
    # 2. Rerank with Vertex AI
    # 3. Return top_k with metadata and citations
    pass
```

### 3. Slack Integration

**Files:**
- `backend/slack/bolt_app.py` — Slack Bolt application entry point
- `backend/slack/handlers/message_handler.py` — DM and mention message handling
- `backend/slack/handlers/command_handler.py` — `/product ask` slash command
- `backend/slack/blocks/qa_response.py` — Block Kit response builders for Q&A

**Slack → ADK Integration:**
```python
# backend/slack/bolt_app.py
from slack_bolt import App
from google.adk.runners import Runner

app = App(token=os.environ["SLACK_BOT_TOKEN"], signing_secret=os.environ["SLACK_SIGNING_SECRET"])

runner = Runner(
    app_name="product-copilot",
    agent=root_agent,
    session_service=redis_session_service,
)

@app.event("app_mention")
def handle_mention(event, say, client):
    thread_ts = event.get("thread_ts") or event["ts"]

    # Ephemeral ack immediately
    client.chat_postEphemeral(
        channel=event["channel"],
        user=event["user"],
        text="🧠 Looking into this... I'll respond in the thread shortly."
    )

    # Enqueue for async ADK processing
    redis_client.lpush("slack:pending", json.dumps({
        "workspace_id": workspace_id,
        "channel_id": event["channel"],
        "thread_ts": thread_ts,
        "user_id": event["user"],
        "text": event["text"],
        "event_ts": event["ts"],
    }))

@app.event("message")
def handle_dm(event, say, client):
    # Handle DMs — same pattern as mentions
    pass

# Async worker (Cloud Run job or secondary Cloud Run service)
async def process_slack_message(payload: dict):
    async for event in runner.run_live(
        user_id=payload["user_id"],
        session_id=payload["thread_ts"],
        new_message=payload["text"],
    ):
        if event.is_final_response:
            await slack_client.chat_postMessage(
                channel=payload["channel_id"],
                thread_ts=payload["thread_ts"],
                text=event.text,
                blocks=build_qa_blocks(event),
            )
```

**Interaction Surface:**
| Trigger | Response |
|---|---|
| `@product-copilot` in channel | Thread reply |
| `/product ask [question]` | Thread reply |
| Thread reply to bot | Continue thread context |

### 4. RAG Pipeline

**Files:**
- `backend/rag/pipeline.py` — Ingestion pipeline orchestration
- `backend/rag/chunker.py` — Domain-specific chunking (PRD, release notes, README)
- `backend/rag/embedder.py` — Vertex AI embedding service
- `backend/rag/retriever.py` — Hybrid retrieval (vector + keyword + reranking)
- `backend/rag/query_rewriter.py` — Gemini-based query expansion
- `backend/rag/ingestion/manual_ingester.py` — Manual document ingestion CLI

**Vertex AI Vector Search Setup:**
```python
# backend/rag/vector_search.py
from google.cloud import aiplatform

aiplatform.init(
    project="product-copilot-prod",
    location="us-central1",
)

# Create matching index
index = aiplatform.MatchingEngineIndex.create(
    display_name="product-copilot-knowledge",
    dimensions=1024,
    approximate_neighbors_count=50,
    index_update_method="STREAM_INCREMENTAL",
)

# Index endpoint
index_endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
    display_name="product-copilot-index-endpoint",
    public_endpoint_enabled=True,
)

index_endpoint.deploy_index(
    index=index,
    deployed_index_id="product-copilot-index",
)
```

**Embedding Service (Vertex AI):**
```python
# backend/rag/embedder.py
from vertexai.generative_models import GenerativeModel
import vertexai.language_models as textmodels

def embed_text(texts: List[str]) -> List[List[float]]:
    embedding_model = textmodels.TextEmbeddingModel.from_pretrained(
        "text-embedding-004"
    )
    embeddings = embedding_model.get_embeddings(texts)
    return [e.values for e in embeddings]
```

**Ingestion (Manual, Phase 1):**
```bash
# CLI: python -m backend.rag.ingestion.manual_ingester \
#   --file path/to/doc.md --source github --product-area payments

# Flow:
# 1. Parse document (Markdown/PDF/text)
# 2. Chunk: 1500 tokens, 200 overlap, section-aware
# 3. Embed: Vertex AI text-embedding-004
# 4. Upsert to Vertex AI Vector Search index
# 5. Store metadata in Cloud SQL knowledge_documents table
```

**Retrieval Pipeline:**
```
Query → Query Rewriter (Gemini: expand abbreviations)
     → [Vertex AI Vector Search (top 30) + PostgreSQL BM25 (top 30)]
     → Reciprocal Rank Fusion (k=60) → Top 15
     → Vertex AI reranking or Cohere rerank → Top 5
     → Gemini 2.5 Flash: synthesize answer with citations
```

**Chunking Strategy (Phase 1):**
| Document Type | Chunk Size | Overlap |
|---|---|---|
| PRD / Spec | 1500 tokens | 200 tokens |
| Release notes | 500 tokens | 50 tokens |
| README | 1000 tokens | 150 tokens |
| General docs | 800 tokens | 100 tokens |

Section-aware splitting: preserve H1/H2 headers with their content.

### 5. Data Layer (GCP-native)

**Files:**
- `backend/db/postgres.py` — Async PostgreSQL via asyncpg
- `backend/db/redis_client.py` — Memorystore (Redis) client
- `backend/db/migrations/001_initial_schema.sql` — Initial tables
- `backend/models/document.py` — Pydantic models for documents

**Cloud SQL Connection:**
```python
# backend/db/postgres.py
from google.cloud.sql.connector import Connector
import asyncpg

connector = Connector()
pool = await asyncpg.create_pool(
    host=connector.connect("product-copilot-prod", "pg8000",
        user="copilot-user", password=secret_version.access_string,
        database="productcopilot"),
    min_size=5, max_size=20,
)
```

**Memorystore (Redis) Session:**
```python
# backend/db/redis_client.py
import redis
from google.cloud.redis_v1 import RedisClient

redis_client = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=6379,
    password=os.environ["REDIS_PASSWORD"],
    ssl=True,
)
```

**PostgreSQL Tables (Phase 1):**
```sql
CREATE TABLE slack_workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slack_team_id VARCHAR(20) UNIQUE NOT NULL,
    bot_token_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slack_user_id VARCHAR(20) NOT NULL,
    workspace_id UUID REFERENCES slack_workspaces(id),
    display_name VARCHAR(255),
    email VARCHAR(255),
    team VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(slack_user_id, workspace_id)
);

CREATE TABLE knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL,
    source_url TEXT,
    title VARCHAR(500),
    content_hash VARCHAR(64),
    product_area VARCHAR(100),
    team_owner VARCHAR(100),
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    vector_index_id TEXT,           -- Vertex AI Vector Search ID
    version VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE conversation_context (
    thread_ts VARCHAR(30) PRIMARY KEY,
    workspace_id UUID REFERENCES slack_workspaces(id),
    channel_id VARCHAR(20),
    turns JSONB DEFAULT '[]',
    current_agent VARCHAR(50),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 6. Observability (GCP-native)

**Files:**
- `backend/observability/logging.py` — Cloud Logging configuration
- `backend/observability/tracing.py` — Cloud Trace (OpenTelemetry) setup
- `backend/observability/metrics.py` — Cloud Monitoring custom metrics

**Cloud Logging:**
```python
# backend/observability/logging.py
import google.cloud.logging
from google.cloud.logging_v2.resource import Resource

client = google.cloud.logging.Client()
client.setup_logging(
    resource=Resource(type="cloud_run_revision", labels={
        "service_name": "product-copilot-backend",
        "revision_name": os.environ["K_REVISION"],
        "location": "us-central1",
    })
)

import structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()
```

**Cloud Trace (OpenTelemetry):**
```python
# backend/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

trace.set_tracer_provider(TracerProvider())
span_exporter = CloudTraceSpanExporter()
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(span_exporter)
)
```

**Cloud Monitoring Metrics:**
```python
# backend/observability/metrics.py
from google.cloud.monitoring_v3 import MetricServiceClient
from google.api import metric_pb2 as ga_metric

# Custom metrics: copilot.response.latency, copilot.llm.errors, copilot.rag.retrieval.latency
# Stored in Cloud Monitoring
# Alert policies configured via GCP Console or Terraform
```

**Dashboards (Cloud Monitoring):**
- Request count, error rate
- Response latency histogram (p50, p95, p99)
- LLM call cost estimate (Vertex AI usage)
- Redis connection pool usage

### 7. Configuration

**Files:**
- `config/prompts/system_product_qa.md` — System prompt for Q&A sub-agent
- `config/prompts/intent_classifier.md` — Few-shot classifier examples
- `config/prompts/root_agent.md` — Root agent instruction prompt
- `config/prompts/sub_agents/product_qa.md` — Product Q&A sub-agent prompt
- `infra/terraform/` — Terraform IaC files
- `.env.example` — Environment variable template
- `config.yaml` — Application configuration

---

## Tech Stack (Phase 1 — GCP + ADK)

| Component | GCP Service | Product |
|---|---|---|
| Agent framework | Google ADK | Agent Development Kit |
| LLM | Vertex AI | Gemini 2.5 Flash |
| Embeddings | Vertex AI | text-embedding-004 |
| Vector DB | Vertex AI | Vector Search |
| Reranking | Vertex AI | (or Cohere rerank) |
| Compute | Cloud Run | Serverless containers |
| Database | Cloud SQL | PostgreSQL 16 |
| Cache | Memorystore | Redis 7 |
| Object storage | Cloud Storage | GCS |
| Secrets | Secret Manager | — |
| Logging | Cloud Logging | — |
| Monitoring | Cloud Monitoring + Trace | — |
| IaC | Terraform | — |

---

## File Structure (Phase 1 Only)

```
product-copilot/
├── backend/
│   ├── agents/
│   │   ├── root_agent.py               # ADK Root Agent (Router)
│   │   ├── sub_agents/
│   │   │   ├── __init__.py
│   │   │   └── product_qa_agent.py     # ADK Sub-Agent (Product Q&A)
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── retrieval_tools.py       # ADK Tool: RAG retrieval
│   │       └── session_tools.py        # ADK Tool: conversation context
│   ├── slack/
│   │   ├── bolt_app.py                 # Slack Bolt + ADK integration
│   │   ├── handlers/
│   │   │   ├── message_handler.py
│   │   │   └── command_handler.py
│   │   └── blocks/
│   │       └── qa_response.py
│   ├── rag/
│   │   ├── pipeline.py
│   │   ├── chunker.py
│   │   ├── embedder.py                 # Vertex AI embeddings
│   │   ├── vector_search.py           # Vertex AI Vector Search
│   │   ├── retriever.py
│   │   ├── query_rewriter.py
│   │   └── ingestion/
│   │       └── manual_ingester.py
│   ├── db/
│   │   ├── postgres.py                # Cloud SQL (asyncpg)
│   │   ├── redis_client.py            # Memorystore
│   │   └── migrations/
│   │       └── 001_initial_schema.sql
│   ├── models/
│   │   └── document.py
│   ├── observability/
│   │   ├── logging.py                 # Cloud Logging + structlog
│   │   ├── tracing.py                 # Cloud Trace + OpenTelemetry
│   │   └── metrics.py                 # Cloud Monitoring
│   └── main.py                        # FastAPI + Cloud Run entry point
├── infra/
│   └── terraform/
│       ├── main.tf                   # Core GCP resources
│       ├── cloud_run.tf              # Cloud Run service
│       ├── cloud_sql.tf              # Cloud SQL instance
│       ├── memorystore.tf            # Memorystore Redis
│       ├── vector_search.tf          # Vertex AI Vector Search
│       ├── secret_manager.tf         # Secrets
│       └── variables.tf
├── config/
│   └── prompts/
│       ├── root_agent.md
│       ├── sub_agents/
│       │   └── product_qa.md
│       └── intent_classifier.md
├── tests/
│   ├── unit/
│   │   ├── test_chunker.py
│   │   ├── test_retriever.py
│   │   └── test_agents.py
│   └── integration/
│       └── test_rag_pipeline.py
├── .env.example
├── config.yaml
├── requirements.txt
├── Dockerfile
└── docker-compose.yml                # Local dev only
```

---

## Success Criteria

- Bot answers 50+ questions in week 8 (staging)
- > 60% user satisfaction (👍 vs 👎 on answers)
- All answers include citations pointing to ingested documents
- Response latency: ephemeral ack within 1s, full answer within 30s (p95)
- Unit test coverage: > 80% on core RAG pipeline
- Zero P0 bugs in staging
- Cloud Run deployment successful with zero downtime

---

## Getting Started Order

1. **Set up GCP project** — Enable APIs (Cloud Run, Cloud SQL, Memorystore, Vertex AI, Secret Manager, Cloud Logging)
2. **Terraform infrastructure** — Provision Cloud SQL, Memorystore, Vertex AI Vector Search, Secret Manager
3. **Bootstrap Slack Bolt app** — OAuth, event subscriptions, slash commands
4. **Implement ADK Root Agent** — Router with Product Q&A sub-agent
5. **Implement ephemeral ack → async response** — prove the pattern works
6. **Build manual ingester** — ingest 3–5 seed documents → Vertex AI Vector Search
7. **Implement RAG pipeline** — chunk → embed → retrieve → synthesize
8. **Add citation rendering** — Block Kit response with sources
9. **Add conversation context** — Memorystore-backed session memory
10. **Add observability** — Cloud Logging, Cloud Trace, Cloud Monitoring
11. **Deploy to Cloud Run** — Docker image, Cloud Run, environment from Secret Manager
12. **Test end-to-end** — real Slack messages against real documents
