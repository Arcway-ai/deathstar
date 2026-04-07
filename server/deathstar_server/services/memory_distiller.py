from __future__ import annotations

import json
import logging
from dataclasses import dataclass

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

_SUGGEST_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Given a conversation between a user and an AI assistant, "
    "identify 3-5 discrete, reusable pieces of knowledge worth remembering for future work on this codebase. "
    "Think of these like entries in a CLAUDE.md or project guidelines file — specific, actionable tips, "
    "patterns, decisions, or conventions that were established or discovered in this conversation.\n\n"
    "Each memory should be:\n"
    "- Self-contained (understandable without the original conversation)\n"
    "- Specific (not generic advice — tied to this codebase/project)\n"
    "- Actionable (helps guide future coding decisions)\n"
    "- Concise (1-3 sentences max)\n\n"
    "Respond with a JSON array of objects. Each object has:\n"
    '- "content": string — the memory text\n'
    '- "tags": string[] — 1-3 short tags (e.g. "architecture", "convention", "gotcha", "pattern")\n\n'
    "Example output:\n"
    '[\n'
    '  {"content": "The auth middleware skips token validation for /health and /web/api/static/* routes.", "tags": ["auth", "convention"]},\n'
    '  {"content": "Use SQLModel Session context managers for all DB operations — never hold sessions across await boundaries.", "tags": ["database", "pattern"]}\n'
    ']\n\n'
    "Respond ONLY with the JSON array, no other text."
)


@dataclass(frozen=True)
class SuggestedMemory:
    content: str
    tags: list[str]


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
    except (anthropic.APIError, anthropic.APIConnectionError, anthropic.AuthenticationError,
            IndexError, AttributeError, TypeError) as exc:
        logger.warning("Memory distillation failed (%s), saving raw content", type(exc).__name__, exc_info=True)
        return response[:_MAX_DISTILLED_CHARS]


async def suggest_memories(
    messages: list[dict[str, str]],
    api_key: str,
) -> list[SuggestedMemory]:
    """Analyze a conversation and suggest 3-5 discrete memories to save.

    Returns a list of SuggestedMemory objects. On failure, returns an empty list.
    """
    # Build a condensed conversation transcript
    transcript_parts: list[str] = []
    for msg in messages[-20:]:  # Last 20 messages max
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:3000]
        transcript_parts.append(f"**{role}**: {content}")
    transcript = "\n\n".join(transcript_parts)

    if not transcript.strip():
        return []

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=_DISTILL_MODEL,
            max_tokens=2048,
            system=_SUGGEST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}],
        )
        raw_text = message.content[0].text.strip()

        # Parse JSON — handle markdown code fences if present
        if raw_text.startswith("```"):
            # Strip ```json ... ``` wrapper
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        items = json.loads(raw_text)
        if not isinstance(items, list):
            logger.warning("suggest_memories: expected list, got %s", type(items).__name__)
            return []

        suggestions: list[SuggestedMemory] = []
        for item in items[:8]:  # Cap at 8 suggestions
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [str(t) for t in tags[:5]]
            suggestions.append(SuggestedMemory(content=content[:_MAX_DISTILLED_CHARS], tags=tags))

        return suggestions
    except (anthropic.APIError, anthropic.APIConnectionError, anthropic.AuthenticationError) as exc:
        logger.warning("suggest_memories API call failed (%s)", type(exc).__name__, exc_info=True)
        return []
    except (json.JSONDecodeError, IndexError, AttributeError, TypeError, KeyError) as exc:
        logger.warning("suggest_memories parse failed (%s)", type(exc).__name__, exc_info=True)
        return []
