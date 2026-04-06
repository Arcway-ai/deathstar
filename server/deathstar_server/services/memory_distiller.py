from __future__ import annotations

import logging

import anthropic

logger = logging.getLogger(__name__)

_DISTILL_MODEL = "claude-haiku-4-5-20251001"
_MAX_DISTILLED_CHARS = 2000

_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Given a user prompt and an AI response, "
    "extract the key learnings, decisions, patterns, or facts worth remembering. "
    "Be concise — output a few bullet points or short paragraphs. "
    "Focus on what would be useful context for future conversations about this codebase. "
    "Do NOT include pleasantries, summaries of the conversation flow, or meta-commentary. "
    "Just the substance."
)


async def distill_memory(prompt: str, response: str, api_key: str) -> str:
    """Distill a raw AI response into concise, memorable content.

    Returns distilled text on success, or the original response (truncated)
    on failure so the memory is still saved.
    """
    user_message = (
        f"## User Prompt\n{prompt[:2000]}\n\n"
        f"## AI Response\n{response[:8000]}"
    )
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=_DISTILL_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        distilled = message.content[0].text[:_MAX_DISTILLED_CHARS]
        return distilled
    except Exception:
        logger.warning("Memory distillation failed, saving raw content", exc_info=True)
        return response[:_MAX_DISTILLED_CHARS]
