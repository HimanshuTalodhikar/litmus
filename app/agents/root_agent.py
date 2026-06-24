"""
Product Copilot Root Agent.
Uses CodeMax (Anthropic-compatible /v1/messages API) for LLM calls.
Uses RAG (Qdrant + local embeddings) for product knowledge.
Routes feature requests to the Feature Intake Agent.
"""

import json
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.rag.retriever import retrieve

settings = get_settings()


def _build_client() -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=settings.codermax_api_key,
        base_url=settings.codermax_base_url,
    )


def _build_system_prompt(include_context: bool, context_chunks: list[dict] | None = None) -> str:
    """Build the system prompt, optionally including retrieved product docs."""
    base = """You are the Product Copilot assistant for this company.

Your job is to answer questions about the company's products accurately and helpfully.
Be concise, friendly, and accurate. If you don't know something, say so. Also you are the product Copilot so keep this in mind when someone asks who you are."""

    if not include_context or not context_chunks:
        return base

    sections = []
    for chunk in context_chunks:
        source = chunk.get("source", "unknown")
        heading = chunk.get("heading", "")
        content = chunk.get("content", "")
        sections.append(f"## {source}" + (f" — {heading}" if heading else ""))
        sections.append(content)

    context_block = "\n\n".join(sections)
    return (
        f"{base}\n\n"
        f"## Product Knowledge Base\n"
        f"The following information comes from the company's internal product documentation. "
        f"Use it to answer the user's question. If the question isn't covered by this data, "
        f"say you don't have that information.\n\n"
        f"{context_block}"
    )


async def chat(message: str, history: list[dict], user_id: str = None,
               channel_id: str = None, thread_ts: str = None) -> str:
    """
    Send a chat message to the LLM and return the response text.
    History is a list of {role, content} dicts.
    Uses RAG to retrieve relevant product docs before answering.
    Routes feature requests to the Feature Intake Agent.
    """
    # Fast keyword detection — no API call needed
    kw_result = _keyword_intent(message)
    if kw_result == "feature_request":
        from app.agents.feature_intake_agent import run_feature_intake
        return await run_feature_intake(
            message=message,
            workspace_id="default",
            requester_id=user_id or "unknown",
            slack_channel_id=channel_id,
            slack_thread_ts=thread_ts,
        )

    client = _build_client()

    # Detect intent via LLM if keyword check inconclusive
    intent = await _detect_intent(message, client)
    if intent == "feature_request":
        from app.agents.feature_intake_agent import run_feature_intake
        return await run_feature_intake(
            message=message,
            workspace_id="default",
            requester_id=user_id or "unknown",
            slack_channel_id=channel_id,
            slack_thread_ts=thread_ts,
        )

    # Try to retrieve relevant product docs
    context_chunks = None
    try:
        chunks = retrieve(message, top_k=5)
        if chunks:
            context_chunks = [
                {"source": c.source, "heading": c.heading, "content": c.content}
                for c in chunks
            ]
    except Exception:
        pass  # RAG unavailable — answer without context

    system_prompt = _build_system_prompt(
        include_context=(context_chunks is not None and len(context_chunks) > 0),
        context_chunks=context_chunks,
    )

    messages = [{"role": "user", "content": message}]

    response = await client.messages.create(
        model=settings.codermax_model,
        system=system_prompt,
        messages=messages,
        max_tokens=1024,
    )

    text_parts = [
        block.text for block in response.content if block.type == "text"
    ]
    return " ".join(text_parts)


FR_KEYWORDS = [
    "i want", "we want", "i wish", "we wish",
    "can you add", "please add", "add a", "add the",
    "it would be great", "would be nice", "would be helpful",
    "we need", "i need", "need to be able",
    "make it possible", "please build", "build a",
    "suggestion:", "feature request", "request:",
    "can we get", "could we have", "why doesn",
    "when will", "何时", "please support",
]

def _keyword_intent(message: str) -> str | None:
    """Fast keyword check. Returns 'feature_request' if strong signals found, else None."""
    lower = message.lower()
    score = sum(1 for kw in FR_KEYWORDS if kw in lower)
    return "feature_request" if score >= 1 else None


async def _detect_intent(message: str, client: AsyncAnthropic) -> str:
    """Classify message intent: product_question or feature_request."""
    prompt = (
        "Classify this Slack message as either 'product_question' or 'feature_request'.\n\n"
        "product_question: user is asking about existing products, features, pricing, "
        "how something works, or anything that can be answered from product documentation.\n\n"
        "feature_request: user is describing something they want, a new capability, "
        "an improvement, a missing feature, or expressing a wish/need.\n\n"
        "Return ONLY the word 'product_question' or 'feature_request'.\n\n"
        f"Message: {message}"
    )
    try:
        response = await client.messages.create(
            model=settings.codermax_model,
            system="You are a Slack intent classifier. Return ONLY the word 'product_question' or 'feature_request'.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
        )
        text = " ".join(b.text for b in response.content if b.type == "text").strip().lower()
        if "feature_request" in text:
            return "feature_request"
        return "product_question"
    except Exception:
        return "product_question"
