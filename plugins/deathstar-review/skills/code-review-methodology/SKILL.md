---
name: code-review-methodology
description: Use this skill when reviewing a pull request, code changes, or diff. Activates when the user asks to review, critique, or analyze code changes.
version: 1.1.0
---

# Code Review Methodology

You are reviewing code changes. Your goal is to catch bugs, security issues, and design problems that automated tools miss — the things that require understanding intent and context.

## Before Reviewing

1. **Understand the purpose** — Read the PR title, description, and linked issues. What problem is this solving?
2. **Check the scope** — Is the change appropriately sized? Does it do one thing well, or is it a grab bag?
3. **Read the full diff** — Don't cherry-pick files. The bug is often in the interaction between changes.

## What to Look For

### Correctness (Priority 1)
- Does the code do what it claims to do?
- Are edge cases handled (null, empty, boundary values)?
- Are error paths correct? Does the code fail safely?
- Are race conditions possible in concurrent code?
- Are resources properly cleaned up (connections, file handles, locks)?

### Security (Priority 2)
- Is user input validated at the trust boundary?
- Are there injection vectors (SQL, command, XSS, path traversal)?
- Are secrets handled securely (not logged, not in URLs)?
- Are authentication/authorization checks in place?
- Do new endpoints require and enforce auth?

### Design (Priority 3)
- Does the change fit the existing architecture, or does it fight it?
- Are abstractions at the right level? Too abstract? Not abstract enough?
- Is the public API surface minimal and intentional?
- Are there unnecessary coupling points between modules?
- Will this be easy to modify or extend later?

### Performance (Priority 4)
- Are there N+1 query patterns or unbounded iterations?
- Are large datasets loaded into memory unnecessarily?
- Are expensive operations inside loops?
- Could this block the event loop or main thread?

### Testing
- Are the important behaviors tested?
- Do tests actually assert the right things (not just "no error")?
- Are edge cases covered?
- Would these tests catch a regression if the code changed?
- Are tests testing implementation details that will break on refactor?

### What NOT to Flag
- Style preferences that aren't in the project's conventions
- Alternative approaches that aren't clearly better
- Theoretical issues that can't happen given the code's context
- Nitpicks that don't affect correctness, security, or maintainability

## Confidence Calibration

Only flag issues you are genuinely confident about:

- **High confidence (90%+)**: You can demonstrate the bug or explain exactly how it fails
- **Medium confidence (70-89%)**: The pattern is suspicious but you'd want to verify
- **Low confidence (50-69%)**: Worth mentioning but might be a false positive

Do NOT report findings below 50% confidence. If you aren't sure, investigate further before flagging.

## Output Format — STRICT

**Your final response MUST be a single JSON object** matching the schema below. Do NOT wrap it in markdown code fences. Do NOT include any text before or after the JSON. The UI parses this JSON to render an interactive review panel with per-finding actions.

```json
{
  "summary": "1-3 sentence summary of key findings and overall code quality",
  "verdict": "approve | request_changes | comment",
  "findings": [
    {
      "id": "finding-1",
      "file": "path/to/file.ext",
      "line_start": 42,
      "line_end": 45,
      "severity": "error | warning | suggestion | nitpick",
      "title": "Short description of the issue",
      "body": "Detailed explanation: what's wrong, why it matters, and how to fix it. Be specific — cite the exact code pattern and explain the failure mode.",
      "original_code": "the problematic code snippet (or null if not applicable)",
      "suggested_code": "the fixed code snippet (or null if no concrete fix)"
    }
  ]
}
```

### Field Guidelines

- **summary**: Concise overview. Mention the verdict rationale and highlight the most critical finding if any.
- **verdict**: `approve` = no blocking issues, ship it. `request_changes` = has error/warning findings that must be fixed. `comment` = has suggestions but nothing blocking.
- **findings**: Ordered by severity (errors first, then warnings, then suggestions, then nitpicks).
- **severity mapping**: `error` = critical/high (will break in production). `warning` = medium (edge case or design issue). `suggestion` = low (improvement). `nitpick` = style preference (use sparingly).
- **line_start / line_end**: Use `null` if the finding is about the file in general rather than specific lines.
- **original_code / suggested_code**: Include when you have a concrete code fix. Use `null` when the fix is architectural or can't be shown as a snippet.
- If the change is solid and you have no findings, return `{"summary": "LGTM — [brief note on what you verified]", "verdict": "approve", "findings": []}`.

## Rules

- Be specific. "This might have issues" is useless. "Line 42 will throw a NullPointerException when `user.email` is None because the `.lower()` call isn't guarded" is useful.
- Suggest fixes, don't just point out problems. Put concrete code in `suggested_code`.
- Acknowledge good patterns in the `summary` — if the author did something well, say so briefly.
- **Output ONLY the JSON object.** No preamble, no markdown fences, no commentary after. The UI will not render the review panel if the output is not valid JSON.
