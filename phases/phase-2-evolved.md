# Phase 2 — Evolved: Feature Request Lifecycle (Weeks 9–20)

**Goal:** Full feature request lifecycle from Slack submission through Jira ticket creation and status sync.

**Cloud:** AWS (primary) + CodeMax (Anthropic-compatible API) + Qdrant Cloud (vector DB)

---

## Scope

### In Scope

- Feature Intake Sub-Agent: dedup check, enrichment, scoring, storage (CodeMax)
- Semantic feature deduplication with Qdrant Cloud + PostgreSQL BM25 + reranking
- Priority scoring engine (modified RICE)
- Jira integration: create tickets, sync status changes back to Slack
- Feedback Agent: record corrections, trigger knowledge updates
- Knowledge gap detection + proactive notification to Knowledge Owners
- Automated source connectors: GitHub, Notion, Confluence
- EventBridge for scheduled ingestion + async processing
- Full observability: CloudWatch, CloudWatch Logs, CloudWatch Metrics

### Out of Scope (for Phase 2)

- Plan Generation Agent
- Full multi-turn conversation (beyond 5-turn context)
- Cross-workspace support
- Fine-tuning pipeline
- A/B testing framework

---

## Deliverables

### 1. Feature Request Data Model

**File:** `backend/models/feature_request.py`

```python
# backend/models/feature_request.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4
import enum


class FeatureRequestStatus(str, enum.Enum):
    REQUESTED = "requested"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BACKLOG = "backlog"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    SHIPPED = "shipped"


class FeatureRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    fr_number: int = Field(default=None)  # Human-readable: FR-001, FR-002
    workspace_id: UUID

    # Content
    raw_text: str
    enriched_text: Optional[str] = None
    extracted_intent: Optional[dict] = None

    # Status
    status: FeatureRequestStatus = FeatureRequestStatus.REQUESTED

    # Prioritization
    priority_score: Optional[float] = None  # 0-100
    reach_score: Optional[int] = None       # 1-10
    impact_score: Optional[int] = None      # 1-3
    confidence_score: Optional[float] = None  # 0.5-1.0
    effort_estimate: Optional[str] = None  # "xs", "s", "m", "l", "xl"

    # Deduplication
    dedup_status: str = "pending"  # pending / matched / new
    dedup_match_id: Optional[UUID] = None
    dedup_similarity_score: Optional[float] = None

    # Jira
    jira_issue_key: Optional[str] = None
    jira_issue_url: Optional[str] = None

    # Context
    requester_id: Optional[str] = None  # Slack user ID
    slack_channel_id: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    slack_message_ts: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    shipped_at: Optional[datetime] = None
```

### 2. PostgreSQL Schema

```sql
-- backend/db/migrations/002_feature_requests.sql

CREATE TABLE feature_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fr_number SERIAL UNIQUE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id),

    -- Content
    raw_text TEXT NOT NULL,
    enriched_text TEXT,
    extracted_intent JSONB,

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'requested'
        CHECK (status IN (
            'requested', 'under_review', 'accepted', 'rejected',
            'backlog', 'scheduled', 'in_progress', 'shipped'
        )),

    -- Prioritization
    priority_score NUMERIC(5,2),
    reach_score INTEGER CHECK (reach_score BETWEEN 1 AND 10),
    impact_score INTEGER CHECK (impact_score BETWEEN 1 AND 3),
    confidence_score NUMERIC(3,2),
    effort_estimate VARCHAR(10),

    -- Deduplication
    dedup_status VARCHAR(20) DEFAULT 'pending',
    dedup_match_id UUID REFERENCES feature_requests(id),
    dedup_similarity_score NUMERIC(3,2),

    -- Jira
    jira_issue_key VARCHAR(50),
    jira_issue_url VARCHAR(500),

    -- Context
    requester_id VARCHAR(50),
    slack_channel_id VARCHAR(20),
    slack_thread_ts VARCHAR(30),
    slack_message_ts VARCHAR(30),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    shipped_at TIMESTAMPTZ
);

CREATE INDEX idx_fr_status ON feature_requests(status);
CREATE INDEX idx_fr_jira ON feature_requests(jira_issue_key);
CREATE INDEX idx_fr_workspace ON feature_requests(workspace_id);
CREATE INDEX idx_fr_priority ON feature_requests(priority_score DESC NULLS LAST);
CREATE INDEX idx_fr_created ON feature_requests(created_at DESC);

-- Full-text search for dedup
ALTER TABLE feature_requests ADD COLUMN enriched_text_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(enriched_text, raw_text))) STORED;
CREATE INDEX idx_fr_fulltext ON feature_requests USING GIN(enriched_text_tsv);
```

### 3. Feature Intake ADK Sub-Agent

**File:** `app/agents/feature_intake_agent.py`

```python
# app/agents/feature_intake_agent.py
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.services.dedup_engine import check_duplicates
from app.services.prioritization import score_priority
from app.services.jira_client import create_jira_ticket
from app.models.feature_request import FeatureRequest
import structlog

logger = structlog.get_logger()
settings = get_settings()

_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            api_key=settings.codermax_api_key,
            base_url=settings.codermax_base_url,
        )
    return _client


SYSTEM_PROMPT = """You are the Feature Intake Agent. Your job:

1. When a user describes a feature they want, acknowledge their request
2. Call `check_feature_duplicates` to see if it already exists
   - If similarity > 0.92: return the existing FR with a link
   - If similarity 0.65-0.92: show match and ask for confirmation
   - If similarity < 0.65: proceed to create new FR
3. Call `create_fr_tool` to create a new feature request
4. Call `create_jira_ticket_tool` to create a Jira ticket if score >= 60
5. Return a summary to the user: FR number, priority score, next steps

Always be concise and actionable."""


async def check_feature_duplicates_tool(query: str, workspace_id: str) -> dict:
    """Check if a feature request already exists. Returns duplicate matches."""
    return check_duplicates(query, workspace_id)


async def create_fr_tool(
    raw_text: str,
    enriched_text: str,
    requester_id: str,
    workspace_id: str,
    slack_channel_id: str = None,
    slack_thread_ts: str = None,
) -> dict:
    """Create a new feature request record and score it."""
    from app.db.feature_request_repo import create_feature_request

    fr = FeatureRequest(
        raw_text=raw_text,
        enriched_text=enriched_text,
        requester_id=requester_id,
        workspace_id=workspace_id,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )
    created = create_feature_request(fr)

    # Score priority
    scores = await score_priority(created.id)
    created.priority_score = scores["final_score"]

    return {
        "fr_id": str(created.id),
        "fr_number": created.fr_number,
        "priority_score": created.priority_score,
        "status": created.status.value,
    }


async def create_jira_ticket_tool(fr_id: str) -> dict:
    """Create a Jira ticket for a feature request."""
    return await create_jira_ticket(fr_id)


async def run_feature_intake(message: str, workspace_id: str, requester_id: str,
                              slack_channel_id: str = None, slack_thread_ts: str = None) -> str:
    """
    Run the feature intake flow for a user message.
    Calls CodeMax with tool definitions and handles the response.
    """
    client = _get_client()

    dedup_result = await check_feature_duplicates_tool(message, workspace_id)
    decision = dedup_result.get("decision", "create")

    if decision == "match":
        match = dedup_result["matches"][0]
        return (
            f"This sounds similar to an existing request: *{match.get('fr_number', 'FR')}*\n"
            f"Already submitted by <@{match.get('requester_id', 'someone')}>.\n"
            f"Want to add your vote or thoughts to it instead?"
        )

    # Enrich the request text
    enriched = await _enrich_request(message, client)
    fr_result = await create_fr_tool(
        raw_text=message,
        enriched_text=enriched,
        requester_id=requester_id,
        workspace_id=workspace_id,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )

    jira_result = {}
    if fr_result.get("priority_score", 0) >= 60:
        jira_result = await create_jira_ticket_tool(fr_result["fr_id"])

    summary = (
        f"Got it! I've logged your feature request as *{fr_result['fr_number']}* "
        f"with a priority score of *{fr_result['priority_score']}*/100.\n"
    )
    if jira_result.get("jira_key"):
        summary += f"Jira ticket created: <{jira_result['jira_url']}|{jira_result['jira_key']}>\n"
    summary += "The product team will review it shortly."

    return summary


async def _enrich_request(raw_text: str, client: AsyncAnthropic) -> str:
    """Use CodeMax to extract and expand the feature request."""
    response = await client.messages.create(
        model=settings.codermax_model,
        system="You are a product analyst. Rewrite the following feature request "
               "to be clear, specific, and actionable. Include the expected behavior, "
               "the problem it solves, and the target user. Be concise (2-4 sentences).",
        messages=[{"role": "user", "content": raw_text}],
        max_tokens=256,
    )
    return " ".join(b.text for b in response.content if b.type == "text")
```

### 4. Feature Deduplication Engine

**File:** `app/services/dedup_engine.py`

```python
# app/services/dedup_engine.py
"""
Hybrid feature dedup: vector search (Qdrant) + BM25 (PostgreSQL) + RRF
Uses qdrant-client 1.18.0 API (query_points, PointStruct).
"""

from typing import List, Optional
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.db.qdrant_client import get_qdrant
from app.db.postgres import get_pg_pool
from app.rag.embedder import embed_texts
import structlog

logger = structlog.get_logger()

FR_COLLECTION = "feature_requests"
VECTOR_SIZE = 384


def check_duplicates(query: str, workspace_id: str) -> dict:
    """
    Returns: {"matches": [...], "decision": "create"/"match"/"review"}
    """
    # 1. Embed query
    query_embedding = embed_texts([query])[0]

    # 2. Vector search in Qdrant (dedup index)
    qdrant = get_qdrant()
    try:
        results = qdrant.query_points(
            collection_name=FR_COLLECTION,
            query=query_embedding,
            limit=5,
            score_threshold=0.3,
            query_filter=Filter(
                must=[FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))]
            ),
            with_payload=True,
        )
    except Exception:
        results = None

    vector_hits = []
    if results and hasattr(results, "points"):
        for r in results.points:
            vector_hits.append({
                "id": str(r.id),
                "payload": r.payload,
                "score": r.score,
            })

    # 3. BM25 via PostgreSQL
    pg = get_pg_pool()
    try:
        bm25_results = pg.fetch("""
            SELECT id, fr_number, enriched_text,
                   ts_rank_cd(enriched_text_tsv, plainto_tsquery('english', $1)) AS bm25_score
            FROM feature_requests
            WHERE workspace_id = $2
              AND status NOT IN ('rejected')
            ORDER BY bm25_score DESC
            LIMIT 5
        """, query, workspace_id)
    except Exception:
        bm25_results = []

    # 4. RRF fusion
    fused = _reciprocal_rank_fusion(
        vector_results=vector_hits,
        bm25_results=list(bm25_results),
    )

    # 5. Decision
    if not fused:
        return {"matches": [], "decision": "create", "confidence": 1.0}

    top_score = fused[0]["score"]

    if top_score >= 0.92:
        return {"matches": [fused[0]], "decision": "match", "confidence": top_score}
    elif top_score >= 0.65:
        return {"matches": fused[:3], "decision": "review", "confidence": top_score}
    else:
        return {"matches": [], "decision": "create", "confidence": 1.0 - top_score}


def _reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    """RRF fusion of two ranked result lists."""
    scores = {}
    seen = {}

    # Vector results (ranked by Qdrant score)
    for i, result in enumerate(vector_results):
        doc_id = result["id"]
        rrf = 1.0 / (k + i + 1)
        scores[doc_id] = scores.get(doc_id, 0) + rrf
        seen[doc_id] = {**result["payload"], "vector_score": result["score"], "id": doc_id}

    # BM25 results
    for i, row in enumerate(bm25_results):
        doc_id = str(row["id"])
        rrf = 1.0 / (k + i + 1)
        scores[doc_id] = scores.get(doc_id, 0) + rrf
        if doc_id not in seen:
            seen[doc_id] = {"id": doc_id, "fr_number": row["fr_number"], "text": row["enriched_text"]}

    # Sort and normalize
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    max_score = scores[sorted_ids[0]] if sorted_ids else 1

    return [
        {**seen[doc_id], "score": scores[doc_id] / max_score}
        for doc_id in sorted_ids
    ]
```

### 5. Prioritization Engine

**File:** `app/services/prioritization.py`

```python
# app/services/prioritization.py
"""
Modified RICE scoring: (Reach × Impact × Confidence) / Effort
Uses CodeMax API (Anthropic-compatible) for scoring.
"""

import json
import re
from anthropic import AsyncAnthropic
from app.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            api_key=settings.codermax_api_key,
            base_url=settings.codermax_base_url,
        )
    return _client


async def score_priority(feature_request_id: str) -> dict:
    """
    Score a feature request using the RICE framework.
    CodeMax assists with estimating Reach, Impact, Confidence, Effort.
    """
    from app.db.feature_request_repo import get_feature_request
    client = _get_client()

    fr = await get_feature_request(feature_request_id)

    prompt = f"""Score this feature request using the RICE framework.

Feature request: {fr.enriched_text or fr.raw_text}

Estimate:
- Reach (1-10): How many users impacted per quarter? (10 = most users)
- Impact (1-3): Business impact where 3 = revenue or strategic direction change
- Confidence (0.5-1.0): How certain are you of these estimates?
- Effort (1-13): Engineering effort in weeks

Return ONLY valid JSON:
{{"reach": N, "impact": N, "confidence": N.N, "effort": N}}

JSON:"""

    try:
        response = await client.messages.create(
            model=settings.codermax_model,
            system="You are a product analyst. Return ONLY valid JSON.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=128,
        )
        text = " ".join(b.text for b in response.content if b.type == "text")
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            scores = json.loads(json_match.group())
        else:
            scores = {"reach": 5, "impact": 2, "confidence": 0.5, "effort": 5}

        rice = (scores["reach"] * scores["impact"] * scores["confidence"]) / scores["effort"]
        final_score = min(rice * 10, 100)  # Normalize to 0-100

        return {
            **scores,
            "rice_raw": rice,
            "final_score": round(final_score, 1),
        }
    except Exception as e:
        logger.error("prioritization_error", error=str(e))
        return {"final_score": 50, "reach": 5, "impact": 2, "confidence": 0.5, "effort": 5}
```

### 6. Jira Integration

**File:** `backend/services/jira_client.py`

```python
# backend/services/jira_client.py
"""
Jira REST API client for creating and updating tickets.
"""

import httpx
from app.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()


class JiraClient:
    def __init__(self):
        self.base_url = settings.jira_url
        self.email = settings.jira_email
        self.api_token = settings.jira_api_token
        self.project_key = settings.jira_project_key

    def _headers(self):
        return {
            "Authorization": f"Basic {self._auth()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _auth(self):
        import base64
        creds = f"{self.email}:{self.api_token}"
        return base64.b64encode(creds.encode()).decode()

    async def create_ticket(self, fr: dict) -> dict:
        """Create a Jira ticket from a feature request."""
        priority_label = self._map_priority(fr.get("priority_score", 50))

        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": f"[FR-{fr['fr_number']}] {self._extract_title(fr['raw_text'])}",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Original request:**\n{fr['raw_text']}"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Enriched:**\n{fr.get('enriched_text', 'N/A')}"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Submitted by:** <@{fr.get('requester_id', 'unknown')}>"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Priority score:** {fr.get('priority_score', 'N/A')}/100"}
                            ]
                        },
                    ]
                },
                "issuetype": {"name": "Feature"},
                "priority": {"name": priority_label},
                "labels": ["slack-captured", "auto-generated"],
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "jira_key": data["key"],
                "jira_url": f"{self.base_url}/browse/{data['key']}",
            }

    def _map_priority(self, score: float) -> str:
        if score >= 80: return "Highest"
        if score >= 60: return "High"
        if score >= 40: return "Medium"
        return "Low"

    def _extract_title(self, text: str) -> str:
        # First sentence or first 80 chars
        import re
        first_sentence = re.split(r'[.!?]', text)[0].strip()
        return first_sentence[:80] if first_sentence else text[:80]
```

### 7. EventBridge for Scheduled Syncs

**File:** `infra/terraform/eventbridge.tf`

```hcl
# infra/terraform/eventbridge.tf

# Daily GitHub docs sync
resource "aws_cloudwatch_event_rule" "github_daily_sync" {
  name        = "product-copilot-github-daily-sync"
  description = "Trigger daily GitHub docs ingestion"
  schedule_expression = "cron(0 2 * * ? *)"  # 2am UTC daily
}

resource "aws_cloudwatch_event_target" "github_sync" {
  rule      = aws_cloudwatch_event_rule.github_daily_sync.name
  target_id = "github-sync"
  arn       = aws_ecs_service.backend.target_group_arn  # Triggers ECS task
  ecs_parameters {
    task_definition_arn = aws_ecs_task_definition.backend.arn
    task_count          = 1
    launch_type         = "FARGATE"
  }
}

# Weekly Confluence sync
resource "aws_cloudwatch_event_rule" "confluence_weekly_sync" {
  name        = "product-copilot-confluence-weekly-sync"
  schedule_expression = "cron(0 3 ? * SUN *)"  # Sunday 3am UTC
}

# Jira webhook → SNS → SQS → ECS
resource "aws_sns_topic" "jira_events" {
  name = "product-copilot-jira-events"
}

resource "aws_sqs_queue" "jira_events" {
  name = "product-copilot-jira-events"
}

resource "aws_sns_topic_subscription" "jira_to_sqs" {
  topic_arn = aws_sns_topic.jira_events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.jira_events.arn
}
```

### 8. Full File List (Phase 2)

```
app/
├── agents/
│   ├── feature_intake_agent.py       # NEW: feature intake + dedup + scoring
│   └── feedback_agent.py             # NEW
├── models/
│   └── feature_request.py              # NEW
├── services/
│   ├── dedup_engine.py               # NEW: Qdrant + PostgreSQL BM25 + RRF
│   ├── prioritization.py             # NEW: RICE scoring via CodeMax
│   └── jira_client.py               # NEW: Jira REST API
├── connectors/
│   ├── github_connector.py            # NEW
│   ├── notion_connector.py           # NEW
│   └── confluence_connector.py       # NEW
├── db/
│   └── migrations/
│       └── 002_feature_requests.sql  # NEW
├── workers/
│   └── jira_webhook_worker.py       # NEW
└── routers/
    └── feature_requests.py           # NEW: /api/v1/feature-requests

infra/terraform/
├── eventbridge.tf                    # NEW: EventBridge + SNS/SQS
└── outputs.tf                        # UPDATED
```

---

## Success Criteria

- 20+ FRs captured via Slack
- ≥ 5 Jira tickets created automatically
- Dedup catch rate > 70% (spot-checked by PM)
- PM reviews ≤ 5/day
- Jira → Slack status sync < 60s
- User feedback positive rate ≥ 70%
