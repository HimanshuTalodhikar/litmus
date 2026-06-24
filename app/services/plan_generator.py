"""
Plan Generator Service — generates implementation plans and phases using Claude Sonnet via CodeMax.
Uses httpx directly to avoid SDK timeout issues.
"""
import httpx
import json
import re
from pathlib import Path

from app.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

# Resolve paths relative to project root (one level up from app/)
_ROOT = Path(__file__).resolve().parent.parent.parent
IMPL_DIR = _ROOT / "impl"
PHASES_DIR = _ROOT / "phases"


async def _call_llm(prompt: str, max_tokens: int = 8192) -> str:
    """Call CodeMax LLM via httpx directly."""
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
    )
    try:
        resp = await client.post(
            f"{settings.codermax_base_url}/v1/messages",
            headers={
                "Authorization": f"Bearer {settings.codermax_api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "anthropic-dangerous-direct-browser-access": "true",
            },
            json={
                "model": settings.codermax_model or "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        text = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text", "")
            elif isinstance(block, str):
                text += block
        return text
    finally:
        await client.aclose()


def _ensure_dirs():
    IMPL_DIR.mkdir(exist_ok=True)
    PHASES_DIR.mkdir(exist_ok=True)


def _slug(text: str) -> str:
    """Sluggify text for filenames."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]


async def generate_implementation_plan(
    fr_id: str,
    fr_number: int,
    raw_text: str,
    enriched_text: str | None,
    priority_score: float | None,
) -> dict:
    """
    Generates:
      - impl/FR-{n}-plan.md        — overall implementation plan
      - phases/FR-{n}-phase-{n}.md — one file per phase

    Returns dict with plan_path, phase_count, phase_paths.
    """
    _ensure_dirs()

    fr_desc = raw_text.strip()
    if enriched_text:
        fr_desc += f"\n\nAI Summary: {enriched_text.strip()}"
    if priority_score:
        fr_desc += f"\n\nPriority Score: {priority_score:.1f}/100"

    # ── Prompt to generate the overall plan ─────────────────────────────────
    plan_prompt = f"""You are a senior software architect. Generate a detailed, production-quality implementation plan for the following feature request.

## Feature Request
{fr_desc}

## Instructions
Write a comprehensive implementation plan. Structure it as follows:

# Implementation Plan — FR-{fr_number}

## Context
Brief description of what this feature does and why it matters.

## Architecture
High-level architecture decisions, technology choices, and system design.

## File Structure
Show the complete directory/file tree that needs to be created or modified.

## Implementation Phases
Break the work into 2–6 logical phases. For EACH phase, give:
- **Phase name** (e.g., Phase 1: Foundation)
- **Goal** — what this phase achieves
- **Files to create/modify** — list of specific files
- **Key decisions** — any design choices made here
- **Verification** — how to verify this phase works

Label phases clearly as "## Phase 1: ...", "## Phase 2: ...", etc.

## Key Technical Decisions
List and explain the major technical decisions (language, framework, DB, etc.).

## Verification Plan
How to test the full feature end-to-end once all phases are complete.

Be concrete and specific. Use real file paths and real code snippets where helpful.
The plan should be actionable by a skilled engineer.
"""

    logger.info("plan_generator.calling_llm", fr=fr_number)
    plan_text = await _call_llm(plan_prompt)
    logger.info("plan_generator.plan_done", fr=fr_number, plan_len=len(plan_text))

    # Save the overall plan
    plan_path = IMPL_DIR / f"FR-{fr_number}-plan.md"
    plan_path.write_text(plan_text)
    logger.info("plan_generator.plan_saved", path=str(plan_path))

    # ── Parse phases from plan and generate individual phase files ────────────
    phase_pattern = re.compile(
        r"^##\s+Phase\s+(\d+):\s+(.+)$", re.MULTILINE
    )
    phase_starts = [(m.start(), m.group(1), m.group(2)) for m in phase_pattern.finditer(plan_text)]

    phase_paths = []
    if len(phase_starts) >= 2:
        # Generate a dedicated file per phase
        phase_prompts = []
        for idx, (start, num, name) in enumerate(phase_starts):
            end = phase_starts[idx + 1][0] if idx + 1 < len(phase_starts) else len(plan_text)
            phase_body = plan_text[start:end].strip()
            phase_paths.append((num, name, phase_body))

        for (phase_num, phase_name, phase_body) in phase_paths:
            phase_file = PHASES_DIR / f"FR-{fr_number}-phase-{phase_num}.md"
            phase_slug = _slug(phase_name)
            phase_file.write_text(
                f"# Phase {phase_num}: {phase_name}\n\n"
                f"> FR-{fr_number} · {phase_name}\n\n"
                f"{phase_body}\n\n"
                f"---\n*Generated from: impl/FR-{fr_number}-plan.md*\n"
            )
            logger.info("plan_generator.phase_saved", path=str(phase_file))
    else:
        # Single phase or no phases detected — save the whole plan as phase-1
        phase_file = PHASES_DIR / f"FR-{fr_number}-phase-1.md"
        phase_file.write_text(
            f"# Implementation: {fr_desc.splitlines()[0]}\n\n"
            f"> FR-{fr_number}\n\n"
            f"{plan_text}\n\n"
            f"---\n*Generated from: impl/FR-{fr_number}-plan.md*\n"
        )
        phase_paths = [(1, "Implementation", plan_text)]
        logger.info("plan_generator.phase_fallback", path=str(phase_file))

    return {
        "fr_id": fr_id,
        "fr_number": fr_number,
        "plan_path": str(plan_path),
        "phase_count": len(phase_paths),
        "phase_paths": [str(PHASES_DIR / f"FR-{fr_number}-phase-{p[0]}.md") for p in phase_paths],
    }
