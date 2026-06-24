import logging
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/slack", tags=["slack"])
logger = logging.getLogger(__name__)
settings = get_settings()


class SlackChallenge(BaseModel):
    challenge: str


@router.post("/events")
async def slack_events(request: Request):
    """Handle Slack Event Subscriptions webhook — includes URL verification challenge."""
    body = await request.body()
    data = json.loads(body)

    # Slack URL verification
    if "challenge" in data:
        return JSONResponse(content={"challenge": data["challenge"]})

    # Handle event callback
    event_type = data.get("event", {}).get("type", "unknown")
    logger.info("slack_event_received", event_type=event_type)

    # Enqueue for async processing
    try:
        from app.workers.queue_publisher import publish_event_sync
        publish_event_sync("slack_events", data)
    except Exception as e:
        logger.exception("failed_to_publish_event")

    return JSONResponse(content={"ok": True})


@router.post("/commands")
async def slack_commands(request: Request):
    """Handle Slack slash commands."""
    form_data = await request.form()
    command = form_data.get("command", "")
    text = form_data.get("text", "")
    user_id = form_data.get("user_id", "")
    channel_id = form_data.get("channel_id", "")
    trigger_id = form_data.get("trigger_id", "")

    logger.info("slack_command_received", command=command, text=text, user_id=user_id)

    payload = {
        "command": command,
        "text": text,
        "user_id": user_id,
        "channel_id": channel_id,
        "trigger_id": trigger_id,
    }

    try:
        from app.workers.queue_publisher import publish_event_sync
        publish_event_sync("slack_commands", payload)
    except Exception as e:
        logger.exception("failed_to_publish_command")

    # Respond immediately (Slack expects a response within 3 seconds)
    return JSONResponse(content={
        "response_type": "ephemeral",
        "text": "Working on it...",
    })


@router.post("/interactions")
async def slack_interactions(request: Request):
    """Handle Slack interactive components (buttons, select menus, etc.)."""
    form_data = await request.form()
    payload_str = form_data.get("payload", "{}")
    payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str

    action_type = payload.get("type", "unknown")
    logger.info("slack_interaction", type=action_type)

    try:
        from app.workers.queue_publisher import publish_event_sync
        publish_event_sync("slack_interactions", payload)
    except Exception as e:
        logger.exception("failed_to_publish_interaction")

    return JSONResponse(content={"ok": True})
