import logging
from slack_sdk.web.async_client import AsyncWebClient
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def handle_slash_command(command: str, text: str, user_id: str, channel_id: str, trigger_id: str) -> dict:
    """
    Handle /product slash command.
    Returns a Slack formatted response dict.
    """
    client = AsyncWebClient(token=settings.slack_bot_token)

    logger.info("slash_command", command=command, text=text, user=user_id)

    if command == "/product":
        subcommand = text.split()[0] if text else ""
        remainder = " ".join(text.split()[1:]) if len(text.split()) > 1 else ""

        if subcommand == "ask":
            return {
                "response_type": "in_channel",
                "text": f"Processing your question: {remainder or text}...",
            }
        elif subcommand == "request":
            return {
                "response_type": "ephemeral",
                "text": f"Feature request flow coming soon: {remainder or text}",
            }
        elif subcommand == "help":
            return {
                "response_type": "ephemeral",
                "text": "*Product Copilot Help*\n\n"
                        "`/product ask <question>` — Ask a product question\n"
                        "`/product request <description>` — Submit a feature request\n"
                        "`/product help` — Show this help",
            }
        else:
            return {
                "response_type": "ephemeral",
                "text": f"Unknown command. Try `/product help` for available commands.",
            }

    return {
        "response_type": "ephemeral",
        "text": "Unknown command.",
    }
