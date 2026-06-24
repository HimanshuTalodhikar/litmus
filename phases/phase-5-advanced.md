# Phase 5 — Advanced: Autonomous Agents, Voice, and Platform (Weeks 49–60)

**Goal:** Autonomous workflows, voice interface, plugin ecosystem, and self-serve admin console.

**Cloud:** AWS (primary) + GCP Vertex AI + Qdrant Cloud

---

## Scope

### In Scope

- Autonomous agentic workflows (proactive insights, change detection)
- Voice interface (AWS Polly or equivalent)
- Plugin / skill system
- Self-serve admin console
- Proactive notifications
- Public API for third-party integrations
- Mobile web app
- Vertex AI fine-tuning for domain embeddings

---

## Deliverables

### 1. Autonomous Agentic Workflows

```python
# backend/adk/autonomous_agent.py
"""
Scheduled agent that proactively surfaces insights.
Runs via EventBridge Scheduler daily.
"""

class AutonomousAgent:
    """
    Proactive behaviors:
    1. Change detection: notify users when docs they asked about are updated
    2. Trend detection: flag trending knowledge gaps
    3. Weekly digest: personalized summary to each active user
    4. Roadmap change alerts: notify FR requesters when their feature changes
    """

    async def on_document_updated(self, doc_id: str, topic: str):
        recent_askers = await db.fetch("""
            SELECT DISTINCT user_id FROM conversations
            WHERE created_at > NOW() - INTERVAL '30 days'
            AND query ILIKE %s
        """, f"%{topic}%")

        for user in recent_askers:
            await slack_client.chat_postMessage(
                channel=user.slack_id,
                text=f"📝 Update: the {topic} doc was just updated!"
            )

    async def generate_weekly_digest(self, workspace_id: str):
        for user in await get_active_users(workspace_id):
            digest = await build_digest(user)
            await slack_client.chat_postMessage(
                channel=user.slack_id,
                blocks=build_digest_blocks(digest)
            )
```

### 2. Voice Interface

```python
# backend/voice/voice_handler.py
"""
Voice: AWS Polly for synthesis, Whisper for transcription.
Alternative: GCP Cloud Speech-to-Text + Cloud TTS.
"""

import boto3

polly = boto3.client("polly")


def synthesize_speech(text: str) -> bytes:
    response = polly.synthesize_speech(
        Text=text,
        OutputFormat="ogg_vorbis",
        VoiceId="Joanna",  # Neural voice
        Engine="neural",
    )
    return response["AudioStream"].read()
```

### 3. Plugin / Skill System

```python
# backend/plugins/plugin_manager.py
"""
ADK tools as extendable Skills.
Workspace admins can enable/disable skills without code changes.
Skills stored as configs in S3.
"""

class SkillRegistry:
    def get_tools_for_workspace(self, workspace_id: str) -> list[Tool]:
        enabled = self.get_enabled_skills(workspace_id)
        return [self.load_skill(skill_id) for skill_id in enabled]

    def load_skill(self, skill_id: str) -> Tool:
        skill_config = self.get_skill_config(skill_id)
        # Dynamically load skill handler from S3 or local
        return self._build_tool(skill_config)


# Built-in skills:
# - jira-reporter: "status of FR-123"
# - customer-health: "health of Acme Corp"
# - usage-analytics: "usage for dark mode"
# - competitive-analysis: "vs CompetitorX"
```

### 4. Public API

```python
# backend/routers/public_api.py
"""
REST API for third-party integrations.
Protected by API key (stored in Secrets Manager).
Rate limited: 100 req/min per key.
"""

from fastapi import APIRouter, Security
from fastapi.security import APIKeyHeader

router = APIRouter(prefix="/api/v1", tags=["public"])
api_key_header = APIKeyHeader(name="X-API-Key")


@router.get("/query")
async def query(q: str, api_key: str = Security(api_key_header)):
    verify_api_key(api_key)
    return await chat_via_runner(message=q, user_id="api", app_name="product-copilot-api")


@router.post("/feature-requests")
async def create_fr(req: CreateFRRequest, api_key: str = Security(api_key_header)):
    verify_api_key(api_key)
    return await create_feature_request(req)


@router.get("/feature-requests/{fr_id}")
async def get_fr(fr_id: str, api_key: str = Security(api_key_header)):
    verify_api_key(api_key)
    return await get_feature_request(fr_id)
```

---

## Success Criteria

- Proactive alerts ≥ 50 times/week
- Voice interface handles ≥ 20% of mobile queries
- ≥ 5 custom skills installed
- Admin console used by ≥ 80% of admins
- ≥ 3 third-party integrations built
