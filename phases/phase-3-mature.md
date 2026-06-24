# Phase 3 — Mature: Production-Hardened with Continuous Learning (Weeks 21–36)

**Goal:** Production-grade with implementation plan generation, full multi-turn conversation, automated knowledge curation, and continuous learning.

**Cloud:** AWS (primary) + GCP Vertex AI (ADK) + Qdrant Cloud

---

## Scope

### In Scope

- Plan Generation ADK Sub-Agent: multi-phase implementation plans
- Full multi-turn conversation (ADK session memory + Redis)
- Knowledge Curator Agent: gap detection, quality scoring, stale doc flagging
- A/B testing framework for prompt variants
- Fine-tuning pipeline: use feedback data to improve reranker
- Cross-modal dedup: FRs ↔ Jira tickets ↔ knowledge docs
- Web dashboard for FR management
- Full observability: CloudWatch dashboards, alarms, Grafana (optional)

### Out of Scope

- Kafka (EventBridge sufficient through Phase 3)
- Full HA failover automation (Phase 4)
- Multi-workspace support (Phase 4)

---

## Deliverables

### 1. Plan Generation Agent

**File:** `backend/adk/sub_agents/plan_gen_agent.py`

```python
# backend/adk/sub_agents/plan_gen_agent.py
from google.adk.agents import Agent
from google.adk.tools import Tool
from vertexai.generative_models import GenerativeModel

model = GenerativeModel("gemini-2.5-pro")  # Pro for complex planning


def generate_implementation_plan(
    feature_request_id: str,
    target_quarter: str = None,
    num_phases: int = 3,
) -> dict:
    """
    Generate a multi-phase implementation plan for an accepted feature request.
    Uses Gemini Pro for complex reasoning.
    """
    from backend.db.feature_request_repo import get_feature_request
    from backend.rag.retriever import retrieve

    fr = get_feature_request(feature_request_id)
    query = fr.enriched_text or fr.raw_text

    # Retrieve related knowledge
    related = retrieve(query, top_k=5)

    context = "\n".join([
        f"[Source {i+1}]: {r.text[:500]}"
        for i, r in enumerate(related)
    ])

    prompt = f"""You are a senior engineering manager creating an implementation plan.

Feature: {query}
Target quarter: {target_quarter or 'TBD'}
Number of phases: {num_phases}

Generate a phased implementation plan. Each phase must include:
- Phase name and goal
- Effort estimate in engineering weeks
- Dependencies
- Acceptance criteria (how we know it's done)
- Key risks and mitigations

Return valid JSON with this schema:
{{
  "plan_name": "...",
  "target_quarter": "...",
  "total_effort_estimate": "...",
  "phases": [
    {{
      "phase_number": 1,
      "phase_name": "...",
      "description": "...",
      "effort_estimate_weeks": N,
      "dependencies": ["..."],
      "acceptance_criteria": ["..."],
      "risks": ["..."],
      "tasks": [{{"title": "...", "story_points": N, "area": "..."}}]
    }}
  ]
}}
JSON:"""

    response = model.generate_content(prompt)
    import json, re
    match = re.search(r'\{.*\}', response.text, re.DOTALL)
    return json.loads(match.group()) if match else {}


plan_gen_agent = Agent(
    name="plan_gen_agent",
    model="gemini-2.5-pro",
    description="Generates multi-phase implementation plans for accepted feature requests",
    instruction="""
    Generate implementation plans for accepted feature requests.

    Use `generate_implementation_plan` to create a phased plan.
    Store the plan in PostgreSQL and link it to the feature request.
    Return a clear, actionable summary to the user in Slack.
    """,
    tools=[Tool(name="generate_implementation_plan", ...)]
)
```

### 2. Full Multi-Turn Conversation

**Enhancement to RedisSessionService:**

```python
# backend/adk/redis_session_service.py (enhanced)
class RedisSessionService:
    """
    Enhanced: supports long-term conversation context storage.
    """

    MAX_TURNS_IN_MEMORY = 5  # Passed to ADK
    ARCHIVE_AFTER_TURNS = 20

    async def get_conversation_turns(
        self, app_name: str, user_id: str, session_id: str
    ) -> list[dict]:
        """
        Get last N conversation turns for context injection.
        """
        r = await self._get_redis()
        key = f"adk:convo:{app_name}:{user_id}:{session_id}"
        turns = await r.lrange(key, -self.MAX_TURNS_IN_MEMORY, -1)
        return [json.loads(t) for t in turns]

    async def append_turn(
        self, app_name: str, user_id: str, session_id: str,
        role: str, content: str
    ):
        """Append a turn and trim to MAX_TURNS_IN_MEMORY."""
        r = await self._get_redis()
        key = f"adk:convo:{app_name}:{user_id}:{session_id}"
        await r.lpush(key, json.dumps({"role": role, "content": content}))
        await r.ltrim(key, 0, self.MAX_TURNS_IN_MEMORY - 1)
        await r.expire(key, 86400)  # 24h TTL
```

### 3. Knowledge Curator Agent

**File:** `backend/adk/knowledge_curator_agent.py`

```python
# backend/adk/knowledge_curator_agent.py
from google.adk.agents import Agent

knowledge_curator_agent = Agent(
    name="knowledge_curator_agent",
    model="gemini-2.5-flash",
    description="Detects knowledge gaps, scores document quality, flags stale content",
    instruction="""
    Run daily to maintain the knowledge base quality.

    Daily tasks:
    1. Aggregate knowledge gaps from past 24h, group by product area
    2. Flag product areas with >= 3 gaps (urgent)
    3. Detect documents not updated in 60+ days (stale)
    4. Score document quality: citation_rate + positive_feedback_rate
    5. Post digest to #product-knowledge Slack channel

    Monthly tasks:
    - Generate comprehensive knowledge report
    - Recommend documents to create or update
    """,
    tools=[
        get_knowledge_gaps_tool,
        score_document_quality_tool,
        detect_stale_documents_tool,
        post_digest_tool,
    ]
)
```

### 4. Cross-Modal Dedup

```python
# backend/services/cross_modal_dedup.py
"""
Phase 3: Search across FRs, Jira tickets, AND knowledge docs simultaneously.
"""

from typing import List
from app.db.qdrant_client import get_qdrant
from app.rag.embedder import embed_text
from app.db.postgres import get_pg_pool

COLLECTIONS = {
    "knowledge": "product_copilot_knowledge",
    "feature_requests": "product_copilot_feature_requests",
    "jira_shipped": "product_copilot_jira_shipped",  # New in Phase 3
}


def cross_modal_search(query: str, workspace_id: str) -> dict:
    """
    Search across all collections and return unified results.
    """
    qdrant = get_qdrant()
    embedding = embed_text(query)

    all_results = []
    for collection_name, collection in COLLECTIONS.items():
        try:
            results = qdrant.search(
                collection_name=collection,
                query_vector=embedding,
                limit=3,
                query_filter={
                    "must": [
                        {"key": "workspace_id", "match": {"value": workspace_id}}
                    ] if "workspace_id" in qdrant.get_collection(collection).config.params else []
                },
                with_payload=True,
            )
            for r in results:
                all_results.append({
                    **r.payload,
                    "collection": collection_name,
                    "score": r.score,
                })
        except Exception:
            pass

    # Sort by score
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:5]
```

### 5. A/B Testing Framework

```python
# backend/services/ab_testing.py
"""
ADK prompt variant testing.
Variants stored in S3 as JSON configs.
"""

import json
import hashlib
from app.db.s3_client import get_s3_client

BUCKET = "product-copilot-config"


def get_prompt_variant(agent_name: str, user_id: str) -> str:
    """
    Route user to a prompt variant based on user_id hash.
    Ensures consistent routing (same user always gets same variant).
    """
    s3 = get_s3_client()
    manifest_key = f"prompts/{agent_name}/manifest.json"

    try:
        manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=manifest_key)["Body"].read())
    except Exception:
        return "default"

    bucket = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100
    cumulative = 0

    for variant_id, config in manifest.get("variants", {}).items():
        cumulative += config.get("traffic_split", 0.5) * 100
        if bucket < cumulative:
            return variant_id

    return "default"


def track_variant_performance(
    agent_name: str,
    variant_id: str,
    user_id: str,
    metric: str,  # "satisfaction", "confidence", "latency"
    value: float,
):
    """Log variant performance to CloudWatch."""
    from app.observability.metrics import track_ab_metric
    track_ab_metric(
        metric_name=f"ab.{agent_name}.{variant_id}.{metric}",
        value=value,
        dimensions={"agent": agent_name, "variant": variant_id}
    )
```

### 6. Web Dashboard

```
frontend/
├── app/
│   ├── dashboard/page.tsx         # FR Kanban board
│   ├── fr/[id]/page.tsx          # FR detail + plan
│   ├── analytics/page.tsx         # Metrics dashboard
│   └── knowledge/page.tsx         # Document management
└── package.json
```

Deployed to ECS Fargate (separate service), accessible at `dashboard.productcopilot.ai`.

---

## Success Criteria

- ≥ 80% of accepted FRs have a generated plan within 24h
- Context maintained across 20+ turn conversations
- ≥ 80% of knowledge gaps resolved within 7 days
- ≥ 2 prompt variants tested
- Dashboard used by ≥ 80% of PMs
