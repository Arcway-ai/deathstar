---
name: implementation-planning
description: Use this skill when creating an implementation plan, designing a feature, architecting a solution, or breaking down a task into steps. Activates when the user asks to plan, design, architect, or scope work.
version: 1.1.0
---

# Implementation Planning Methodology

You are creating a structured implementation plan. The goal is a plan that someone can execute without needing to ask clarifying questions — specific enough to be actionable, concise enough to be useful.

## Before Planning

1. **Clarify the goal** — What does "done" look like? What's the acceptance criteria?
2. **Understand constraints** — Timeline, backward compatibility, performance requirements, existing patterns
3. **Explore the codebase** — Read the relevant files before proposing changes. Don't plan changes to code you haven't read.

## Planning Methodology

Use this methodology to guide your thinking. Do NOT output these sections as prose — they feed into the structured JSON output below.

### Context & Architecture
- What problem are we solving and why now?
- What's the current state of the code? What prior art or patterns exist?
- State the approach clearly. Briefly explain why it was chosen over alternatives you actually considered.

### File Changes
For each file affected, know:
- Action (Create / Modify / Delete), exact path, what specifically changes and why
- Order by implementation sequence — what needs to happen first

### Data Model Changes
If the plan involves schema changes, API contract changes, or new data structures:
- Exact field definitions with types
- Migration strategy (if modifying existing schema)
- Backward compatibility considerations

### Testing Strategy
- What needs unit tests? What needs integration tests?
- What edge cases must be covered?

## Output Format — STRICT

**Your final response MUST be a single JSON object** matching the schema below. Do NOT wrap it in markdown code fences. Do NOT include any text before or after the JSON. The UI parses this JSON to render an interactive plan panel with a Save button.

```json
{
  "title": "Short descriptive title for the plan",
  "overview": "1-3 sentence summary: what problem this solves, the chosen approach, and why. Include architecture decisions and trade-offs here.",
  "complexity": "low | medium | high",
  "phases": [
    {
      "id": "phase-1",
      "name": "Phase name",
      "description": "What this phase accomplishes and why it comes first",
      "tasks": [
        {
          "id": "phase-1-task-1",
          "title": "Action verb + what (e.g. 'Add session validation to auth middleware')",
          "description": "2-3 sentences: what to do, which files to change, how to verify. Be concrete — file paths, function names, field types.",
          "files": ["path/to/file1.py", "path/to/file2.ts"],
          "effort": "small | medium | large"
        }
      ]
    }
  ],
  "risks": [
    "Concrete risk: what could go wrong and what assumption it depends on"
  ],
  "open_questions": [
    "Specific question that needs answering before or during implementation"
  ]
}
```

### Field Guidelines

- **title**: Under 80 characters. Describe the feature/change, not "Implementation Plan".
- **overview**: This is where architecture decisions, trade-offs, and context go. The reader should understand the "why" from this field alone.
- **complexity**: `low` = isolated change, few files. `medium` = cross-cutting, multiple components. `high` = architectural change, schema migrations, multi-phase rollout.
- **phases**: Group tasks into logical phases ordered by dependency. Each phase should be deployable/testable independently where possible.
- **tasks**: Each task should be atomic (completable in one session) and testable. Put file paths in the `files` array — every file the task touches.
- **effort**: `small` = under 30 min. `medium` = 1-3 hours. `large` = half day or more.
- **risks**: Real risks, not boilerplate. "Might break existing tests" is vague. "The `UserSession` model change requires an Alembic migration that must run before the new endpoint is deployed" is useful.
- **open_questions**: Things you couldn't determine from reading the code. Empty array `[]` is fine if there are none.

## Plan Quality Checklist

Before outputting the JSON, verify:

- [ ] Every file mentioned actually exists (or the task explicitly says "Create")
- [ ] The implementation order makes sense (no forward dependencies)
- [ ] Each task is small enough to complete and verify independently
- [ ] The plan doesn't over-engineer — it solves the stated problem, not hypothetical future problems
- [ ] Schema/API changes include migration strategy in the task description
- [ ] The plan accounts for existing tests that might break

## Rules

- **Read before planning.** Use Read, Glob, and Grep to understand the codebase. Plans based on assumptions about code structure are useless.
- **Be concrete.** "Refactor the auth module" is not a task. "Add a `validate_session()` method to `session.py` that checks HMAC signature and expiry" is a task.
- **Scope ruthlessly.** If something is nice-to-have but not required, mention it in `open_questions` or omit it entirely.
- **Don't plan what you can just do.** If a task takes less than 5 minutes, it doesn't need a plan step — just do it.
- **Surface trade-offs.** Every architectural decision has downsides. State them in the `overview` so the reader knows what they're trading away.
- **Output ONLY the JSON object.** No preamble, no markdown fences, no commentary after. The UI will not render the plan panel if the output is not valid JSON.
