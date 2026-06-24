"""
Modified RICE scoring: (Reach × Impact × Confidence) / Effort
Uses CodeMax API (Anthropic-compatible) for scoring.
"""
import json
import re
from anthropic import AsyncAnthropic
from app.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

_client: AsyncAnthropic | None = None


def _extract_rice_scores(raw_text: str) -> dict | None:
    """
    Extract RICE scores from raw model output.
    Handles:
      - Flat:    {"reach": 8, "impact": 3, "confidence": 0.8, "effort": 5}
      - Nested:  {"rice": {"reach": 8, "impact": 3, "confidence": 0.8, "effort": 5}}
      - Wrapped: {"rice": {"reach": 8, "impact": 3, "confidence": 0.8, "effort": 5}, "score": 3.6}
    """
    if not raw_text:
        return None
    # Strip markdown code fences
    text = re.sub(r'```json\s*', '', raw_text.strip())
    text = re.sub(r'```\s*$', '', text.strip())

    # Try to find a top-level JSON object
    start = text.find('{')
    if start == -1:
        return None
    # Find the matching closing brace (simple bracket balance)
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    candidate = text[start:end]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    # Navigate to the scores
    # Flat
    if all(k in obj for k in ("reach", "impact", "confidence", "effort")):
        return obj
    # Nested in "rice" key
    if "rice" in obj and isinstance(obj["rice"], dict):
        inner = obj["rice"]
        if all(k in inner for k in ("reach", "impact", "confidence", "effort")):
            return inner
    return None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            api_key=settings.codermax_api_key,
            base_url=settings.codermax_base_url,
        )
    return _client


async def score_priority(feature_request_id: str) -> dict:
    """
    Score a feature request using the RICE framework.
    CodeMax assists with estimating Reach, Impact, Confidence, Effort.
    """
    from app.db.feature_request_repo import get_feature_request
    client = _get_client()

    fr = await get_feature_request(feature_request_id)
    if not fr:
        return {"final_score": 50, "reach": 5, "impact": 2, "confidence": 0.5, "effort": 5}

    prompt = f"""Score this feature request using the RICE framework.

Feature request: {fr.enriched_text or fr.raw_text}

Estimate:
- Reach (1-10): How many users impacted per quarter? (10 = most users)
- Impact (1-3): Business impact where 3 = revenue or strategic direction change
- Confidence (0.5-1.0): How certain are you of these estimates?
- Effort (1-13): Engineering effort in weeks

Return ONLY valid JSON:
{{"reach": N, "impact": N, "confidence": N.N, "effort": N}}

JSON:"""

    try:
        response = await client.messages.create(
            model=settings.codermax_model,
            system=(
                "You are a product analyst. Estimate RICE scores for a feature request.\n\n"
                "IMPORTANT: Return ONLY a raw JSON object with exactly these keys: "
                "reach (integer 1-10), impact (integer 1-3), confidence (float 0.5-1.0), effort (integer 1-13 weeks).\n\n"
                "Return ONLY the JSON — no explanation, no markdown, no code fences."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        # Filter to text blocks only (skip thinking blocks)
        text_parts = []
        for b in response.content:
            if b.type == "text":
                text_parts.append(b.text.strip())
        raw_text = " ".join(text_parts)

        # Extract and parse JSON — handle both flat {"reach":...} and nested {"rice":{...}}
        scores = _extract_rice_scores(raw_text)
        if scores is None:
            logger.warning("prioritization_no_json", raw=raw_text[:200])
            scores = {"reach": 5, "impact": 2, "confidence": 0.5, "effort": 5}

        # Validate and clamp values
        reach = max(1, min(10, int(scores.get("reach", 5))))
        impact = max(1, min(3, int(scores.get("impact", 2))))
        confidence = max(0.5, min(1.0, float(scores.get("confidence", 0.5))))
        effort = max(1, min(13, int(scores.get("effort", 5))))

        rice = (reach * impact * confidence) / effort
        final_score = min(rice * 10, 100)

        logger.info("rice_scored", reach=reach, impact=impact, confidence=confidence,
                    effort=effort, final_score=round(final_score, 1))

        return {
            "reach": reach,
            "impact": impact,
            "confidence": confidence,
            "effort": effort,
            "rice_raw": round(rice, 3),
            "final_score": round(final_score, 1),
        }
    except Exception as e:
        logger.error("prioritization_error", error=str(e))
        return {"final_score": 50, "reach": 5, "impact": 2, "confidence": 0.5, "effort": 5}
