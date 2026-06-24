"""
Feature Intake Agent — captures feature requests, deduplicates, scores, creates Jira tickets.
Uses CodeMax API (Anthropic-compatible).
"""
import asyncio

from anthropic import AsyncAnthropic
from app.config import get_settings
from app.services.dedup_engine import check_duplicates
from app.services.prioritization import score_priority
from app.services.jira_client import create_jira_ticket
from app.models.feature_request import FeatureRequest
from app.db.feature_request_repo import create_feature_request
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


async def check_feature_duplicates_tool(query: str, workspace_id: str) -> dict:
    """Check if a feature request already exists. Returns duplicate matches."""
    return await check_duplicates(query, workspace_id)


async def create_fr_tool(
    raw_text: str,
    enriched_text: str,
    requester_id: str,
    workspace_id: str,
    slack_channel_id: str = None,
    slack_thread_ts: str = None,
) -> dict:
    """Create a new feature request record and score it."""
    fr = FeatureRequest(
        raw_text=raw_text,
        enriched_text=enriched_text,
        requester_id=requester_id,
        workspace_id=workspace_id,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )
    created = await create_feature_request(fr)

    # Score priority and persist to DB
    from app.db.feature_request_repo import update_feature_request
    scores = await score_priority(str(created.id))
    created.priority_score = scores["final_score"]
    await update_feature_request(
        str(created.id),
        priority_score=scores["final_score"],
        reach_score=scores.get("reach"),
        impact_score=scores.get("impact"),
        confidence_score=scores.get("confidence"),
        effort_estimate=str(scores.get("effort", "")),
    )

    # Upsert embedding to Qdrant for future dedup
    if created.enriched_text:
        from app.rag.embedder import embed_texts
        from app.db.feature_request_repo import upsert_feature_request_embedding
        try:
            emb = embed_texts([created.enriched_text])[0]
            await upsert_feature_request_embedding(str(created.id), emb)
        except Exception:
            pass

    return {
        "fr_id": str(created.id),
        "fr_number": created.fr_number,
        "priority_score": created.priority_score,
        "status": created.status.value,
    }


async def create_jira_ticket_tool(fr_id: str) -> dict:
    """Create a Jira ticket for a feature request."""
    return await create_jira_ticket(fr_id)


async def run_feature_intake(
    message: str,
    workspace_id: str,
    requester_id: str,
    slack_channel_id: str = None,
    slack_thread_ts: str = None,
) -> str:
    """
    Run the feature intake flow for a user message.
    Uses CodeMax to enrich, then deduplicates, creates FR, and optionally creates Jira ticket.
    """
    # Step 1: Check for duplicates
    dedup_result = await check_feature_duplicates_tool(message, workspace_id)
    decision = dedup_result.get("decision", "create")

    if decision == "match":
        match = dedup_result["matches"][0]
        return (
            f"This sounds similar to an existing request: *{match.get('fr_number', 'FR')}*.\n"
            f"Already submitted by <@{match.get('requester_id', 'someone')}>.\n"
            f"Want to add your vote or thoughts to it instead?"
        )

    # Step 1b: Check if the feature already exists in product docs (RAG gate)
    from app.rag.retriever import check_product_exists
    try:
        exists, matching_chunks = check_product_exists(message, top_k=5, score_threshold=0.55)
        if exists:
            doc_lines = []
            for c in matching_chunks:
                doc_lines.append(f"• *{c.source}* — {c.heading or c.content[:100]}")
            doc_info = "\n".join(doc_lines)
            return (
                f"It looks like this feature might already exist in the product!\n\n"
                f"Found these related docs:\n{doc_info}\n\n"
                f"Could you clarify what's missing or what you'd like changed?\n"
                f"That'll help us log the right request for the team."
            )
    except Exception:
        pass  # RAG unavailable — proceed without this gate

    # Step 2: Enrich the request text using CodeMax
    enriched = await _enrich_request(message)

    # Step 3: Create the FR
    fr_result = await create_fr_tool(
        raw_text=message,
        enriched_text=enriched,
        requester_id=requester_id,
        workspace_id=workspace_id,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )

    # Step 4: Create Jira ticket — always (not threshold-based)
    jira_result = {}
    try:
        jira_result = await asyncio.wait_for(
            create_jira_ticket_tool(fr_result["fr_id"]),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        jira_result = {"error": "Jira timed out — check credentials"}
    except Exception as e:
        jira_result = {"error": str(e)}

    summary = (
        f"Got it! I've logged your feature request as *{fr_result['fr_number']}* "
        f"with a priority score of *{fr_result['priority_score']}*/100.\n"
    )
    if jira_result.get("jira_key"):
        summary += f"Jira ticket created: <{jira_result['jira_url']}|{jira_result['jira_key']}>\n"
    elif jira_result.get("error"):
        summary += f"(Jira ticket pending — {jira_result['error']})\n"
    summary += "The product team will review it shortly."

    return summary


async def _enrich_request(raw_text: str) -> str:
    """Use CodeMax to extract and expand the feature request."""
    client = _get_client()
    try:
        response = await client.messages.create(
            model=settings.codermax_model,
            system=(
                "You are a product analyst. Given a user's feature request, produce a concise, "
                "well-structured rewrite in exactly this format:\n\n"
                "**Feature Request: <title>**\n\n"
                "**Target User:** <who needs this>\n\n"
                "**Problem:** <what problem it solves>\n\n"
                "**Expected Behavior:** <what the feature should do>\n\n"
                "Do NOT ask any questions. Do NOT include conversational filler. "
                "Return ONLY the rewritten feature request."
            ),
            messages=[{"role": "user", "content": f"Rewrite this feature request:\n{raw_text}"}],
            max_tokens=300,
        )
        parts = []
        for b in response.content:
            if b.type == "text":
                text = b.text.strip()
                if text:
                    parts.append(text)
        result = " ".join(parts)
        # Fallback if model returned nothing usable
        if not result or len(result) < 20:
            return raw_text
        return result
    except Exception as e:
        logger.warning("enrich_error", error=str(e))
        return raw_text
