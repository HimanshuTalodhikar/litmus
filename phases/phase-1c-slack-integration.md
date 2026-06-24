# Phase 1C — Slack Integration (Days 15–22)

**Goal:** The Slack bot responds to messages in real time. Users can DM the bot or use `/product ask` in a channel and get an AI response.

**Time estimate:** 5–7 days

---

## What This Produces

- Slack app with bot token installed in a workspace
- `/product ask` slash command working
- `@product-copilot` mention in channels working
- Ephemeral "Looking into this..." appears within 1 second
- LLM response posted to Slack thread within 30 seconds
- Multi-turn conversation in a thread (last 5 turns from Redis)

---

## Deliverables

### 1. Create the Slack App

**Steps:**

1. Go to https://api.slack.com/apps → Create New App → From scratch
2. Name: `Product Copilot`, choose your workspace
3. Save the **App Token** (`xapp-...`) — goes in Secrets Manager
4. Save the **Bot Token** (`xoxb-...`) — goes in Secrets Manager

**Enable these features:**

**a) Slash Commands:**
```
Command: /product ask
Request URL: https://YOUR-ALB-DNS/slack/commands
Description: Ask the product copilot a question
```

**b) Event Subscriptions:**
```
Request URL: https://YOUR-ALB-DNS/slack/events
Subscribe to:
  - app_mention
  - message.im
  - message.channels
  - message.groups
```

**c) Bot Permissions (OAuth Scopes):**
```
chat:write
commands
app_mentions:read
im:history
im:read
im:write
channels:history
channels:read
groups:history
groups:read
```

**d) Install to Workspace** → Copy Bot User OAuth Token

### 2. Store Slack Secrets

```bash
# In AWS Secrets Manager, update these secrets:
# product-copilot/slack-bot-token  → xoxb-... (Bot Token)
# product-copilot/slack-signing-secret → signing secret from Basic Info
# product-copilot/slack-app-token  → xapp-... (App-Level Token)
```

### 3. Slack App Module

Create `backend/slack/app.py`:

```python
# backend/slack/app.py
from slack_bolt import App
from slack_bolt.adapter.fastapi import Slack BoltSlackHandler
from app.config import get_settings

settings = get_settings()

# Initialize Slack Bolt app
slack_app = App(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
    raise_error_for_unhandled_request=True,
)

# FastAPI handler for Slack webhooks
from fastapi import FastAPI
from slack_bolt.adapter.fastapi import SlackRequestHandler

app_handler = SlackRequestHandler(app=slack_app)

def get_slack_app() -> App:
    return slack_app
```

### 4. Message Handler

Create `backend/slack/handlers/message_handler.py`:

```python
# backend/slack/handlers/message_handler.py
"""
Handles incoming Slack messages — mentions and DMs.
"""

import re
import structlog
from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError

from app.config import get_settings
from app.slack.blocks.qa_response import build_qa_response_blocks
from app.routers.adk import chat_via_runner

logger = structlog.get_logger()
settings = get_settings()


def extract_bot_mention(text: str) -> str:
    """Remove @product-copilot mention from message text."""
    # Matches <@U12345678|product-copilot>
    cleaned = re.sub(r"<@U\w+\|product-copilot>\s*", "", text)
    return cleaned.strip()


async def handle_mention(event: dict, client: WebClient):
    """
    Handle @product-copilot mention in a channel.
    1. Post ephemeral "thinking" message immediately
    2. Queue for async processing
    3. Post ADK response to thread
    """
    channel_id = event["channel"]
    user_id = event["user"]
    thread_ts = event.get("thread_ts") or event["ts"]
    raw_text = event["text"]

    # Skip bot's own messages
    if event.get("subtype") == "bot_message":
        return

    query = extract_bot_mention(raw_text)
    if not query:
        return

    # 1. Post ephemeral "thinking" message immediately
    try:
        thinking_msg = await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="🧠 Looking into this...",
        )
    except SlackApiError as e:
        logger.error("slack_post_thinking_error", error=str(e))
        return

    # 2. Enqueue to Redis for async processing
    import redis.asyncio as redis
    r = redis.from_url(
        f"redis://:{settings.redis_password}@{settings.redis_host}:6379"
    )
    await r.lpush(
        "copilot:pending_messages",
        __import__("json").dumps({
            "type": "mention",
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "query": query,
            "thinking_ts": thinking_msg["ts"],
        })
    )
    await r.aclose()
    logger.info("message_enqueued", type="mention", user_id=user_id)


async def handle_dm(event: dict, client: WebClient):
    """
    Handle direct messages to the bot.
    Same pattern as handle_mention but without the mention text cleanup.
    """
    channel_id = event["channel"]
    user_id = event["user"]
    thread_ts = event.get("thread_ts") or event["ts"]
    text = event["text"]

    if event.get("subtype") == "bot_message":
        return

    if not text.strip():
        return

    # Post ephemeral thinking
    try:
        thinking_msg = await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="🧠 Let me look that up for you...",
        )
    except SlackApiError as e:
        logger.error("slack_post_dm_thinking_error", error=str(e))
        return

    # Enqueue
    import redis.asyncio as redis
    r = redis.from_url(
        f"redis://:{settings.redis_password}@{settings.redis_host}:6379"
    )
    await r.lpush(
        "copilot:pending_messages",
        __import__("json").dumps({
            "type": "dm",
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "query": text,
            "thinking_ts": thinking_msg["ts"],
        })
    )
    await r.aclose()
    logger.info("dm_enqueued", user_id=user_id)
```

### 5. Slash Command Handler

Create `backend/slack/handlers/command_handler.py`:

```python
# backend/slack/handlers/command_handler.py
"""
Handles /product ask slash command.
"""
import json
import structlog
import redis.asyncio as redis
from slack_sdk.web import WebClient
from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


async def handle_product_ask(command: dict, client: WebClient):
    """
    Handle /product ask [question] slash command.

    1. Acknowledge immediately (within 3s Slack requirement)
    2. Enqueue for async processing
    3. Response posted to thread via async worker
    """
    channel_id = command["channel_id"]
    user_id = command["user_id"]
    thread_ts = command["trigger_id"]  # Used as temporary ID
    query = command["text"].strip()

    if not query:
        return {
            "response_type": "ephemeral",
            "text": "Usage: `/product ask [your question]`\n"
                    "Example: `/product ask How do I reset my password?`",
        }

    # Enqueue to Redis
    r = redis.from_url(
        f"redis://:{settings.redis_password}@{settings.redis_host}:6379"
    )
    await r.lpush(
        "copilot:pending_messages",
        json.dumps({
            "type": "slash_command",
            "channel_id": channel_id,
            "user_id": user_id,
            "query": query,
            "command_ts": thread_ts,
        })
    )
    await r.aclose()

    logger.info("slash_command_enqueued", user_id=user_id, query=query[:50])

    return {
        "response_type": "ephemeral",
        "text": f"🧠 Looking into: *{query[:80]}*\n\nI'll answer in this thread shortly...",
    }
```

### 6. Async Worker

Create `backend/workers/message_worker.py`:

```python
# backend/workers/message_worker.py
"""
Async worker that processes messages from the Redis queue.
Runs as a separate process: python -m app.workers.message_worker
"""

import asyncio
import json
import os
import structlog
import httpx
from slack_sdk.web.async_client import AsyncWebClient

from app.config import get_settings
from app.routers.adk import chat_via_runner

logger = structlog.get_logger()


async def process_message(client: AsyncWebClient, message: dict):
    """Process a single message from the queue."""
    msg_type = message["type"]
    channel_id = message["channel_id"]
    thread_ts = message["thread_ts"]
    user_id = message["user_id"]
    query = message["query"]

    try:
        # Call ADK
        logger.info("processing_message", type=msg_type, user_id=user_id, query=query[:50])

        response_text = await chat_via_runner(
            message=query,
            user_id=user_id,
            app_name="product-copilot",
        )

        # Post to Slack thread
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=response_text,
        )

        logger.info("message_processed", user_id=user_id, response_length=len(response_text))

    except Exception as e:
        logger.error("message_processing_error", error=str(e), user_id=user_id)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Sorry, I ran into an issue: {str(e)[:200]}\n\nPlease try again.",
        )


async def run_worker():
    """Main worker loop — polls Redis queue continuously."""
    import redis.asyncio as redis

    settings = get_settings()
    slack_client = AsyncWebClient(token=settings.slack_bot_token)

    r = redis.from_url(
        f"redis://:{settings.redis_password}@{settings.redis_host}:6379",
        decode_responses=True,
    )

    logger.info("message_worker_started")

    while True:
        try:
            # Blocking pop from Redis list (wait up to 5 seconds)
            result = await r.brpop("copilot:pending_messages", timeout=5)

            if result:
                _, raw_message = result
                message = json.loads(raw_message)
                await process_message(slack_client, message)

        except redis.ConnectionError as e:
            logger.error("redis_connection_error", error=str(e))
            await asyncio.sleep(5)

        except Exception as e:
            logger.error("worker_loop_error", error=str(e))
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
```

### 7. Slack Webhook Routes

Create `backend/slack/bolt_app.py` (FastAPI routes for Slack webhooks):

```python
# backend/slack/bolt_app.py
"""
FastAPI routes that receive Slack webhooks.
Slack sends events to these endpoints.
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import structlog

from app.slack.handlers.message_handler import handle_mention, handle_dm
from app.slack.handlers.command_handler import handle_product_ask
from app.config import get_settings
from slack_sdk import WebClient

logger = structlog.get_logger()
router = APIRouter(prefix="/slack", tags=["slack"])
settings = get_settings()


@router.post("/events")
async def slack_events(request: Request):
    """
    Slack Event API webhook endpoint.
    Slack sends a challenge first, then real events.
    """
    body = await request.json()

    # Handle URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Handle actual events
    client = WebClient(token=settings.slack_bot_token)

    for event in body.get("events", []):
        event_type = event.get("type")

        if event_type == "app_mention":
            await handle_mention(event, client)
        elif event_type == "message" and event.get("channel_type") == "im":
            await handle_dm(event, client)
        elif event_type == "message" and event.get("channel_type") == "channel":
            # Only handle if bot is mentioned
            if "<@U" in event.get("text", ""):
                await handle_mention(event, client)
        else:
            logger.debug("unhandled_event_type", type=event_type)

    return {"ok": True}


@router.post("/commands")
async def slack_commands(request: Request):
    """
    Slack Slash Command webhook endpoint.
    """
    form_data = await request.form()
    command = dict(form_data)

    if command.get("command") == "/product":
        subcommand = command.get("text", "").split()[0] if command.get("text") else ""

        if subcommand == "ask":
            result = await handle_product_ask(command, WebClient(token=settings.slack_bot_token))
            return result
        else:
            return {
                "response_type": "ephemeral",
                "text": (
                    "Available commands:\n"
                    "• `/product ask [question]` — Ask a product question\n"
                    "• `/product help` — Get help"
                ),
            }
    else:
        return {"response_type": "ephemeral", "text": "Unknown command"}


@router.post("/interactions")
async def slack_interactions(request: Request):
    """
    Slack Interactive Components webhook.
    Handles button clicks, modal submissions, etc.
    """
    body = await request.json()
    payload = body.get("payload", {})

    if isinstance(payload, str):
        import json
        payload = json.loads(payload)

    # Handle feedback button clicks (Phase 2)
    # Placeholder for Phase 2
    logger.info("interaction_received", type=payload.get("type"))

    return {"ok": True}
```

### 8. Update main.py

```python
# backend/main.py (updated)
from app.routers import health, adk_router
from app.slack.bolt_app import router as slack_router  # NEW

app.include_router(health.router)
app.include_router(adk_router)
app.include_router(slack_router)  # NEW
```

### 9. Slack Response Blocks (QA Response)

Create `backend/slack/blocks/qa_response.py`:

```python
# backend/slack/blocks/qa_response.py
"""
Slack Block Kit message builders for Q&A responses.
"""

def build_qa_response_blocks(
    question: str,
    answer: str,
    sources: list[dict] = None,
    confidence: float = None,
) -> list[dict]:
    """
    Build a Slack Block Kit message for a Q&A response.

    sources format: [{"title": "...", "url": "...", "excerpt": "..."}]
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Q:* {question}",
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*A:* {answer}",
            }
        },
    ]

    # Add sources if available
    if sources:
        source_text = "*📄 Sources:*\n"
        for i, src in enumerate(sources, 1):
            source_text += f"• <{src['url']}|{src['title']}>\n"
            if src.get("excerpt"):
                source_text += f"  > {src['excerpt'][:100]}...\n"

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": source_text}
        })

    # Add confidence if available
    if confidence is not None:
        conf_pct = int(confidence * 100)
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Confidence: {conf_pct}%"}]
        })

    # Add feedback buttons
    blocks.extend([
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👍 Helpful"},
                    "action_id": "feedback_helpful",
                    "value": "helpful",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👎 Not helpful"},
                    "action_id": "feedback_not_helpful",
                    "value": "not_helpful",
                },
            ]
        }
    ])

    return blocks
```

### 10. Update ECS Task Definition for Worker

Add the worker as a second container in the ECS task, or run it as a separate ECS service.

**Option A: Sidecar in same task (simpler)**
```hcl
# infra/terraform/ecs_task_definition.tf (updated)
# Add worker container alongside backend container

container_definitions = jsonencode([
  {
    name  = "product-copilot-backend"
    image = "${aws_ecr_repository.backend.repository_url}:latest"
    # ... existing config ...
  },
  {
    name  = "product-copilot-worker"
    image = "${aws_ecr_repository.backend.repository_url}:latest"
    command = ["python", "-m", "app.workers.message_worker"]
    essential = false  # Worker can crash without stopping the task
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs/worker"
      }
    }
  }
])
```

### 11. Local Test with Ngrok

For local testing, use ngrok to expose your dev server to Slack:

```bash
# Terminal 1: Start local services
docker compose up

# Terminal 2: Start ngrok
ngrok http 8080

# Copy the ngrok HTTPS URL and set it as:
# Slack App → Event Subscriptions → Request URL
# Slack App → Slash Commands → Request URL

# Terminal 3: Run worker
docker compose exec app python -m app.workers.message_worker
```

### 12. Verification Steps

- [ ] `POST /slack/events` returns `{"challenge": "..."}` when Slack sends verification
- [ ] `POST /slack/commands` returns response when `/product ask` is used
- [ ] Bot posts "🧠 Looking into this..." within 1 second of command
- [ ] ADK response appears in thread within 30 seconds
- [ ] `@product-copilot` mention triggers the same flow
- [ ] DM to bot works without the mention text
- [ ] Worker processes the Redis queue correctly
- [ ] ECS deployment works with both backend + worker containers

---

## Common Issues

| Issue | Fix |
|---|---|
| `SigningSecretVerificationError` | Set `SLACK_SIGNING_SECRET` env var correctly |
| 3-second timeout on slash command | Acknowledge immediately with `return {"text": "..."}`, process async |
| Event not triggering | Enable Event Subscriptions + install app to workspace |
| Worker not picking up messages | Check Redis security group; check `copilot:pending_messages` key exists |
| Thread response going to wrong place | Use `thread_ts` from original event, not a new timestamp |
