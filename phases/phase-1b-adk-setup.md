# Phase 1B — LLM Setup with CodeMax (Days 10–14)

**Goal:** Get the FastAPI app calling CodeMax's Anthropic-compatible API successfully. This confirms the AI layer works before building Slack/RAG on top.

**Time estimate:** 1–2 days

---

## What This Produces

- `anthropic` SDK installed and working
- CodeMax API key configured via `.env`
- A root agent that responds to chat messages via CodeMax (Claude Sonnet)
- `POST /adk/chat` endpoint returning LLM responses
- Redis-backed session storage (conversation context per user/session)

---

## Deliverables

### 1. Install Anthropic SDK

```bash
pip install anthropic>=0.40.0
```

### 2. Add CodeMax Config

**`.env`:**
```bash
CODERMAX_API_KEY=sk-cm-your-key
CODERMAX_BASE_URL=https://api.codemax.pro
CODERMAX_MODEL=claude-sonnet-4-6
```

**`app/config.py`:**
```python
# CodeMax (Anthropic-compatible LLM)
codermax_api_key: str = ""
codermax_base_url: str = "https://api.codemax.pro"
codermax_model: str = "claude-sonnet-4-6"
```

### 3. Root Agent

**`app/agents/root_agent.py`:**
```python
from anthropic import AsyncAnthropic
from app.config import get_settings

settings = get_settings()


def _build_client() -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=settings.codermax_api_key,
        base_url=settings.codermax_base_url,
    )


async def chat(message: str, history: list[dict]) -> str:
    client = _build_client()

    system_prompt = """You are the Product Copilot assistant.

Your current capabilities (Phase 1B):
- Echo test messages
- Answer general questions conversationally

Always be helpful, concise, and accurate."""

    response = await client.messages.create(
        model=settings.codermax_model,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
        max_tokens=1024,
    )

    await client.close()

    text_parts = [
        block.text for block in response.content if block.type == "text"
    ]
    return " ".join(text_parts)
```

### 4. Chat Endpoint

**`app/routers/adk.py`:**
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.agents.root_agent import chat

router = APIRouter(prefix="/adk", tags=["adk"])


class ChatRequest(BaseModel):
    message: str
    user_id: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        response_text = await chat(message=req.message, history=[])
        import uuid
        return ChatResponse(response=response_text, session_id=req.session_id or str(uuid.uuid4()))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")
```

### 5. Register Router in main.py

```python
from app.routers import health, adk

app.include_router(health.router)
app.include_router(adk.router)
```

---

## Verification Checklist

Before moving to Phase 1C:

- [ ] `docker compose up --build` succeeds
- [ ] `GET /health` returns `{"status": "ok", ...}`
- [ ] `POST /adk/chat` returns a Claude response (not an error)
- [ ] Same session_id gets previous context on second call (session storage works)
- [ ] ECS deployment succeeds (`make deploy`)
- [ ] `/adk/chat` works via ALB DNS name

---

## Common Issues

| Issue | Fix |
|---|---|
| `Cannot POST /v1/v1/messages` | Base URL should be `https://api.codemax.pro` (SDK appends `/v1/messages`) |
| `Cannot POST /chat/completions` | CodeMax uses `/v1/messages` (Anthropic format), not OpenAI format |
| `401 Unauthorized` | Check `CODERMAX_API_KEY` is correct and not expired |
| Empty response from model | Check model name — use `claude-sonnet-4-6` not `gemini-2.0-flash` |
| Redis session not persisting | Check ElastiCache security group allows ECS SG |
