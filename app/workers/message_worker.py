"""
Redis queue worker — processes Slack events asynchronously.
Run this as a separate process alongside the FastAPI app:
    python -m app.workers.message_worker
"""
import asyncio
import logging
import logging.config
import signal

from app.config import get_settings
from app.workers.queue_publisher import pop_event
from app.agents.root_agent import chat
from app.agents.feature_intake_agent import run_feature_intake
from slack_sdk.web.async_client import AsyncWebClient

# Use raw stdlib logger — bypasses structlog's BoundLogger which doesn't accept kwargs
logging_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.PlainFormatter",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stderr",
        },
    },
}

try:
    import structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _logger = structlog.get_logger()
except ImportError:
    _logger = logging.getLogger(__name__)

settings = get_settings()
running = True


def signal_handler(signum, frame):
    global running
    _logger.info("worker_shutdown_signal_received", signal=signum)
    running = False


async def process_event(queue_name: str, payload: dict):
    """Route event to the appropriate handler."""
    if queue_name == "slack_events":
        await process_slack_event(payload)
    elif queue_name == "slack_commands":
        await process_slack_command(payload)
    elif queue_name == "slack_interactions":
        await process_slack_interaction(payload)
    elif queue_name == "plan_generation":
        await process_plan_generation(payload)


async def process_slack_event(event: dict):
    """Process a Slack event."""
    event_type = event.get("event", {}).get("type", "unknown")
    _logger.info("processing_slack_event", event_type=event_type)

    client = AsyncWebClient(token=settings.slack_bot_token)

    if event_type == "app_mention":
        inner = event["event"]
        channel_id = inner.get("channel")
        thread_ts = inner.get("thread_ts") or inner.get("ts")
        text = inner.get("text", "")

        # Remove bot mention
        cleaned = text.replace("<@UPLACEHOLDER>", "").strip()
        if not cleaned:
            _logger.info("app_mention_skipped_empty")
            return

        _logger.info("app_mention_processing", channel=channel_id)
        response = await chat(message=cleaned, history=[], user_id=inner.get("user"),
                             channel_id=channel_id, thread_ts=thread_ts)

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=response,
        )
        _logger.info("app_mention_replied", channel=channel_id)

    elif event_type == "message":
        inner = event["event"]
        if inner.get("channel_type") == "im":
            channel_id = inner.get("channel")
            text = inner.get("text", "")
            cleaned = text.strip()
            if not cleaned:
                return

            _logger.info("dm_processing", channel=channel_id)
            response = await chat(message=cleaned, history=[], user_id=inner.get("user"),
                                 channel_id=channel_id)
            await client.chat_postMessage(channel=channel_id, text=response)
            _logger.info("dm_replied", channel=channel_id)


async def process_slack_command(payload: dict):
    """Process a Slack slash command."""
    command = payload.get("command")
    text = payload.get("text", "")
    channel_id = payload.get("channel_id")
    user_id = payload.get("user_id")

    _logger.info("processing_slash_command", command=command, text=text, user=user_id)

    client = AsyncWebClient(token=settings.slack_bot_token)

    if command == "/product":
        response = await chat(message=text, history=[])

        try:
            await client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}>:\n{response}",
            )
            _logger.info("slash_command_replied", command=command, channel=channel_id)
        except Exception as e:
            error_str = str(e)
            _logger.warning("chat_postMessage_failed", error=error_str, channel=channel_id)
            # Try to join the channel if not a member
            if "not_in_channel" in error_str:
                try:
                    await client.conversations_join(channel=channel_id)
                    await client.chat_postMessage(
                        channel=channel_id,
                        text=f"<@{user_id}>:\n{response}",
                    )
                    _logger.info("slash_command_replied_after_join", channel=channel_id)
                    return
                except Exception as e2:
                    _logger.warning("conversations_join_failed", error=str(e2), channel=channel_id)
            # Fallback: DM the user directly
            try:
                await client.chat_postMessage(
                    channel=user_id,
                    text=f"<@{user_id}>:\n{response}",
                )
                _logger.info("slash_command_replied_via_dm", user=user_id)
            except Exception as e2:
                _logger.error("dm_postMessage_failed", error=str(e2), user=user_id)

    elif command == "/fr":
        # Reply immediately so we don't hit Slack's 3-second timeout
        # Then process the full flow async
        try:
            await client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}>: Got it! Processing your feature request...",
            )
        except Exception:
            pass

        # Fire the full intake flow in background — doesn't block the reply
        async def background_fr():
            try:
                response = await run_feature_intake(
                    message=text,
                    workspace_id="default",
                    requester_id=user_id,
                    slack_channel_id=channel_id,
                )
                # Post the result back to Slack
                try:
                    await client.chat_postMessage(
                        channel=channel_id,
                        text=f"<@{user_id}>:\n{response}",
                    )
                    _logger.info("fr_result_replied", channel=channel_id)
                except Exception as e2:
                    _logger.warning("fr_result_post_failed", error=str(e2))
            except Exception as e:
                _logger.exception("fr_background_error", error=str(e))
                try:
                    await client.chat_postMessage(
                        channel=channel_id,
                        text=f"<@{user_id}>: Sorry, something went wrong processing your request. Please try again.",
                    )
                except Exception:
                    pass

        asyncio.create_task(background_fr())
        _logger.info("fr_command_queued", user=user_id, channel=channel_id)
        # Yield to event loop so the background task starts running before we continue
        await asyncio.sleep(0)


async def process_slack_interaction(payload: dict):
    """Process Slack interactive components."""
    action_type = payload.get("type", "unknown")
    _logger.info("processing_interaction", action_type=action_type)


async def process_plan_generation(payload: dict):
    """Generate implementation plan via Claude Opus and update FR record."""
    fr_id = payload.get("fr_id")
    fr_number = payload.get("fr_number")
    _logger.info("plan_gen.started", fr=fr_number)

    try:
        from app.agents.plan_agent import generate_implementation_plan as _generate_plan
        from app.db.feature_request_repo import update_feature_request
        from app.models.feature_request import ImplStatus

        result = await _generate_plan(
            fr_id=fr_id,
            fr_number=fr_number,
            raw_text=payload.get("raw_text", ""),
            enriched_text=payload.get("enriched_text"),
            priority_score=payload.get("priority_score"),
        )
        await update_feature_request(
            fr_id,
            impl_status=ImplStatus.GENERATED,
            impl_plan_path=result["plan_path"],
        )
        _logger.info("plan_gen.completed", fr=fr_number, plan=result["plan_path"])

    except Exception as exc:
        _logger.error("plan_gen.failed", fr=fr_number, error=str(exc))
        try:
            from app.db.feature_request_repo import update_feature_request
            from app.models.feature_request import ImplStatus
            await update_feature_request(
                fr_id,
                impl_status=ImplStatus.FAILED,
                impl_error=str(exc),
            )
        except Exception:
            pass


async def run_worker():
    """Main worker loop."""
    global running
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    _logger.info("message_worker_started")

    while running:
        try:
            # Poll commands queue first (non-blocking) — slash commands are latency-sensitive
            result = await pop_event("slack_commands", timeout=1)
            if result:
                await process_event("slack_commands", result)
                continue

            # Poll events queue (shorter blocking timeout)
            result = await pop_event("slack_events", timeout=2)
            if result:
                await process_event("slack_events", result)
                continue

            # Poll interactions queue (non-blocking)
            result = await pop_event("slack_interactions", timeout=0)
            if result:
                await process_event("slack_interactions", result)
                continue

            # Poll plan generation queue (long timeout — these are slow)
            result = await pop_event("plan_generation", timeout=2)
            if result:
                await process_event("plan_generation", result)

        except asyncio.CancelledError:
            break
        except Exception:
            _logger.exception("worker_error")

    _logger.info("message_worker_stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )
    asyncio.run(run_worker())
