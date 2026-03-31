---
name: implementation-planning
description: Use this skill when creating an implementation plan, designing a feature, architecting a solution, or breaking down a task into steps. Activates when the user asks to plan, design, architect, or scope work.
version: 1.0.0
---

# Implementation Planning Methodology

You are creating a structured implementation plan. The goal is a plan that someone can execute without needing to ask clarifying questions — specific enough to be actionable, concise enough to be useful.

## Before Planning

1. **Clarify the goal** — What does "done" look like? What's the acceptance criteria?
2. **Understand constraints** — Timeline, backward compatibility, performance requirements, existing patterns
3. **Explore the codebase** — Read the relevant files before proposing changes. Don't plan changes to code you haven't read.

## Plan Structure

### 1. Context
- What problem are we solving and why now?
- What's the current state of the code?
- What prior art or patterns exist in the codebase?

### 2. Architecture Decision

State the approach clearly and briefly explain why it was chosen over alternatives.

```
**Approach**: [1-2 sentence description]

**Why this over alternatives**:
- Alternative A was considered but [concrete reason it's worse]
- Alternative B was considered but [concrete reason it's worse]
```

Only include alternatives you actually considered and have real trade-off reasoning for. Don't pad with strawman alternatives.

### 3. Files to Create / Modify

For each file, specify:
- **Action**: Create | Modify | Delete
- **Path**: Exact file path
- **Changes**: What specifically changes and why (not just "update this file")
- **Dependencies**: What other files this depends on or affects

Order files by implementation sequence — what needs to happen first.

### 4. Data Model Changes

If the plan involves schema changes, API contract changes, or new data structures:
- Exact field definitions with types
- Migration strategy (if modifying existing schema)
- Backward compatibility considerations

### 5. Implementation Steps

Numbered steps in execution order. Each step should be:
- **Atomic** — Completable in a single session
- **Testable** — Has a clear way to verify it works
- **Independent where possible** — Minimize cross-step dependencies

For each step:
```
**Step N: [Action verb] [what]**
Files: path/to/file1.py, path/to/file2.py
Description: [2-3 sentences of what to do]
Verification: [How to confirm this step is done correctly]
```

### 6. Testing Strategy

- What needs unit tests? What needs integration tests?
- What edge cases must be covered?
- What's the testing verification command?

### 7. Risks & Unknowns

- What could go wrong?
- What assumptions are we making?
- What do we not know yet and how will we find out?

## Plan Quality Checklist

Before presenting the plan, verify:

- [ ] Every file mentioned actually exists (or is explicitly marked as "Create")
- [ ] The implementation order makes sense (no forward dependencies)
- [ ] Each step is small enough to complete and verify independently
- [ ] The plan doesn't over-engineer — it solves the stated problem, not hypothetical future problems
- [ ] Schema/API changes include migration strategy
- [ ] The plan accounts for existing tests that might break

## Rules

- **Read before planning.** Use Read, Glob, and Grep to understand the codebase. Plans based on assumptions about code structure are useless.
- **Be concrete.** "Refactor the auth module" is not a plan. "Add a `validate_session()` method to `session.py` that checks HMAC signature and expiry" is a plan.
- **Scope ruthlessly.** If something is nice-to-have but not required, put it in a "Future Work" section, not in the plan.
- **Don't plan what you can just do.** If a task takes less than 5 minutes, it doesn't need a plan step — just do it.
- **Surface trade-offs.** Every architectural decision has downsides. State them. The person executing the plan should understand what they're trading away.
