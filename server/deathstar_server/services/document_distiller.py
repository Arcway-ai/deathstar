from __future__ import annotations

import json
import logging

import anthropic

logger = logging.getLogger(__name__)

_DISTILL_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = (
    "You are a plan structuring assistant. Given a conversation where an AI assistant created "
    "an implementation plan, extract and restructure it into the exact JSON format below.\n\n"
    "Your job is to distill the substance — phases, tasks, files, risks — from whatever format "
    "the plan was written in (markdown, prose, bullet points, etc.) into this structured schema.\n\n"
    "Output ONLY a single JSON object matching this schema. No markdown fences, no commentary:\n\n"
    "{\n"
    '  "title": "Short descriptive title (under 80 chars)",\n'
    '  "overview": "1-3 sentence summary: problem, approach, and key trade-offs",\n'
    '  "complexity": "low | medium | high",\n'
    '  "phases": [\n'
    "    {\n"
    '      "id": "phase-1",\n'
    '      "name": "Phase name",\n'
    '      "description": "What this phase accomplishes",\n'
    '      "tasks": [\n'
    "        {\n"
    '          "id": "phase-1-task-1",\n'
    '          "title": "Action verb + what",\n'
    '          "description": "What to do, which files, how to verify",\n'
    '          "files": ["path/to/file.py"],\n'
    '          "effort": "small | medium | large"\n'
    "        }\n"
    "      ]\n"
    "    }\n"
    "  ],\n"
    '  "risks": ["Concrete risk descriptions"],\n'
    '  "open_questions": ["Specific questions needing answers"]\n'
    "}\n\n"
    "Guidelines:\n"
    "- Extract ALL phases and tasks mentioned in the conversation\n"
    "- Preserve file paths exactly as mentioned\n"
    "- If effort/complexity is not stated, infer from context\n"
    "- risks and open_questions can be empty arrays if none were mentioned\n"
    "- Every phase must have at least one task\n"
    "- Output ONLY valid JSON, nothing else"
)


async def distill_plan(
    messages: list[dict[str, str]],
    api_key: str,
) -> dict[str, object] | None:
    """Distill a conversation into a structured plan JSON.

    Takes conversation messages from a plan-workflow session and returns
    a StructuredPlan-compatible dict. Returns None on failure.
    """
    # Build a condensed transcript from the conversation
    transcript_parts: list[str] = []
    for msg in messages[-30:]:  # Last 30 messages for plan context
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:6000]
        transcript_parts.append(f"**{role}**: {content}")
    transcript = "\n\n".join(transcript_parts)

    if not transcript.strip():
        return None

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=_DISTILL_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}],
        )
        raw_text = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:],
            )

        plan = json.loads(raw_text)
        if not isinstance(plan, dict):
            logger.warning("distill_plan: expected dict, got %s", type(plan).__name__)
            return None

        # Validate minimum shape
        if "title" not in plan or "phases" not in plan or not isinstance(plan["phases"], list):
            logger.warning("distill_plan: missing required fields (title, phases)")
            return None

        return plan

    except (anthropic.APIError, anthropic.APIConnectionError, anthropic.AuthenticationError) as exc:
        logger.warning("distill_plan API call failed (%s)", type(exc).__name__, exc_info=True)
        return None
    except (json.JSONDecodeError, IndexError, AttributeError, TypeError, KeyError) as exc:
        logger.warning("distill_plan parse failed (%s)", type(exc).__name__, exc_info=True)
        return None
