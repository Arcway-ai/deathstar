from __future__ import annotations

import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)

_DISTILL_MODEL = "claude-opus-4-20250514"

_MAX_RETRIES = 2

_SYSTEM_PROMPT = """\
You are a plan structuring assistant. Given a conversation where an AI assistant \
created an implementation plan, extract and restructure it into a JSON object.

Your job is to distill the substance — phases, tasks, files, risks — from whatever \
format the plan was written in (markdown, prose, bullet points, etc.) into this \
structured schema.

IMPORTANT: Output ONLY raw JSON. No markdown fences, no commentary, no text before \
or after the JSON object.

Required JSON schema:
{
  "title": "Short descriptive title (under 80 chars)",
  "overview": "1-3 sentence summary: problem, approach, and key trade-offs",
  "complexity": "low | medium | high",
  "phases": [
    {
      "id": "phase-1",
      "name": "Phase name",
      "description": "What this phase accomplishes",
      "tasks": [
        {
          "id": "phase-1-task-1",
          "title": "Action verb + what",
          "description": "What to do, which files, how to verify",
          "files": ["path/to/file.py"],
          "effort": "small | medium | large"
        }
      ]
    }
  ],
  "risks": ["Concrete risk descriptions"],
  "open_questions": ["Specific questions needing answers"]
}

Guidelines:
- Extract ALL phases and tasks mentioned in the conversation
- Preserve file paths exactly as mentioned
- If effort/complexity is not stated, infer from context
- risks and open_questions can be empty arrays if none were mentioned
- Every phase must have at least one task
- complexity must be exactly one of: low, medium, high
- effort must be exactly one of: small, medium, large"""


class DistillError(Exception):
    """Raised when plan distillation fails with a user-facing reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _extract_json(raw_text: str) -> dict:
    """Extract a JSON object from model output, handling markdown fences."""
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Match ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            # Fallback: strip first and last lines
            lines = text.split("\n")
            text = "\n".join(lines[1:]).strip()
            if text.endswith("```"):
                text = text[:-3].strip()

    return json.loads(text)


def _validate_plan(plan: object) -> dict:
    """Validate minimum plan shape, raising DistillError on issues."""
    if not isinstance(plan, dict):
        raise DistillError(
            f"Model returned {type(plan).__name__} instead of a JSON object"
        )

    missing = []
    if "title" not in plan:
        missing.append("title")
    if "phases" not in plan:
        missing.append("phases")
    if missing:
        raise DistillError(
            f"Model output missing required fields: {', '.join(missing)}"
        )

    if not isinstance(plan["phases"], list):
        raise DistillError("'phases' must be an array")

    if len(plan["phases"]) == 0:
        raise DistillError(
            "No phases extracted — the conversation may not contain enough plan detail"
        )

    return plan


async def distill_plan(
    messages: list[dict[str, str]],
    api_key: str,
) -> dict[str, object]:
    """Distill a conversation into a structured plan JSON.

    Takes conversation messages from a plan-workflow session and returns
    a StructuredPlan-compatible dict.

    Raises ``DistillError`` with a user-facing reason on failure.
    """
    # Build a condensed transcript from the conversation
    transcript_parts: list[str] = []
    for msg in messages[-30:]:  # Last 30 messages for plan context
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:8000]
        if content.strip():
            transcript_parts.append(f"**{role}**: {content}")
    transcript = "\n\n".join(transcript_parts)

    if not transcript.strip():
        raise DistillError("Conversation has no readable content to distill")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            message = await client.messages.create(
                model=_DISTILL_MODEL,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": transcript}],
            )
            raw_text = message.content[0].text.strip()

            plan = _extract_json(raw_text)
            return _validate_plan(plan)

        except (anthropic.APIError, anthropic.APIConnectionError) as exc:
            last_error = exc
            logger.warning(
                "distill_plan API error on attempt %d/%d (%s)",
                attempt + 1, _MAX_RETRIES + 1, type(exc).__name__,
                exc_info=True,
            )
            # Retry on transient API errors
            continue
        except anthropic.AuthenticationError as exc:
            logger.warning("distill_plan auth failed: %s", exc)
            raise DistillError("Anthropic API authentication failed") from exc
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "distill_plan JSON parse error on attempt %d/%d: %s",
                attempt + 1, _MAX_RETRIES + 1, exc,
            )
            # Retry — the model sometimes wraps JSON in commentary
            continue
        except DistillError:
            raise
        except (IndexError, AttributeError, TypeError, KeyError) as exc:
            logger.warning("distill_plan unexpected parse error: %s", exc, exc_info=True)
            raise DistillError(f"Failed to parse model response: {exc}") from exc

    # All retries exhausted
    if isinstance(last_error, json.JSONDecodeError):
        raise DistillError(
            "Model returned invalid JSON after multiple attempts — "
            "try rephrasing or adding more detail to the plan"
        )
    if isinstance(last_error, (anthropic.APIError, anthropic.APIConnectionError)):
        raise DistillError(
            f"Anthropic API unavailable ({type(last_error).__name__}) — try again in a moment"
        )
    raise DistillError("Failed to distill plan after multiple attempts")
