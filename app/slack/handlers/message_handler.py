import logging
from slack_sdk.web.async_client import AsyncWebClient
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def handle_app_mention(event: dict, team_id: str) -> None:
    """Handle @mention events — send ephemeral thinking message."""
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    user_id = event.get("user")
    text = event.get("text", "")

    client = AsyncWebClient(token=settings.slack_bot_token)

    # Remove bot mention text
    cleaned_text = text.replace("<@UPLACEHOLDER>", "").strip()

    logger.info("app_mention", channel=channel_id, user=user_id, text=cleaned_text)

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="🤔 Thinking...",
    )


async def handle_message(event: dict, team_id: str) -> None:
    """Handle direct messages to the bot."""
    channel_id = event.get("channel")
    user_id = event.get("user")
    text = event.get("text", "")

    client = AsyncWebClient(token=settings.slack_bot_token)

    logger.info("direct_message", channel=channel_id, user=user_id, text=text)

    await client.chat_postMessage(
        channel=channel_id,
        text="🤔 Thinking...",
    )
