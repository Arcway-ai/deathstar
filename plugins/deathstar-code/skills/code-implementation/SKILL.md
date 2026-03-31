---
name: code-implementation
description: Use this skill when writing, modifying, or implementing code. Activates when the user asks to build, implement, fix, refactor, or write code.
version: 1.0.0
---

# Code Implementation Methodology

You are implementing code changes. Write code that works correctly, handles errors well, and fits naturally into the existing codebase.

## Before Writing Code

1. **Read first.** Read the files you'll modify AND the files that interact with them. Understand the existing patterns before introducing new ones.
2. **Check conventions.** Look at CLAUDE.md, existing code style, naming conventions, error handling patterns, test patterns. Match them.
3. **Understand the data flow.** Trace how data moves through the system. Where does input come from? Where does output go? What transforms happen?

## Implementation Principles

### Match Existing Patterns
- If the codebase uses classes, use classes. If it uses functions, use functions.
- If errors are handled with exceptions, use exceptions. If they use result types, use result types.
- If tests use mocks, use mocks. If they use real dependencies, use real dependencies.
- Don't introduce a new pattern unless the existing one is demonstrably broken.

### Write Minimal Changes
- Change only what's necessary to solve the problem.
- Don't refactor surrounding code unless it's required for your change.
- Don't add features that weren't requested.
- Don't add abstractions for code that's only used once.
- Three similar lines of code is better than a premature abstraction.

### Handle Errors at Boundaries
- Validate user input at the point it enters the system.
- Trust internal function calls — don't defensively check values you just computed.
- Catch specific exceptions, not bare `except Exception`.
- Error messages should tell the user what went wrong and what they can do about it.
- Don't swallow errors silently. Log or propagate.

### Write Testable Code
- If you add a function, add a test.
- If you fix a bug, add a test that would have caught it.
- Tests should test behavior, not implementation.
- Each test should test one thing and have a descriptive name.
- Use the existing test infrastructure — don't introduce new test frameworks or patterns.

## Code Quality Checklist

Before presenting your changes, verify:

- [ ] All new functions have type hints (if the language supports it)
- [ ] Error cases are handled — what happens when the input is null, empty, or invalid?
- [ ] No hardcoded values that should be configuration
- [ ] No secrets, API keys, or credentials in the code
- [ ] No `TODO` or `FIXME` comments left behind (either fix it or don't mention it)
- [ ] The happy path AND error path both work
- [ ] Existing tests still pass
- [ ] New code has test coverage for the important paths

## Common Pitfalls

### Security
- Never use `shell=True` in subprocess calls
- Never build SQL queries with string concatenation
- Never render user input as HTML without escaping
- Always validate file paths against traversal (`..`)
- Always use constant-time comparison for tokens/secrets (`hmac.compare_digest`)

### Performance
- Don't load unbounded data into memory — use pagination or streaming
- Don't make N+1 queries — batch or join instead
- Don't do expensive work inside loops when it could be done once outside
- Don't block the event loop with synchronous I/O in async code

### Reliability
- Close resources you open (connections, files, locks)
- Make operations idempotent where possible
- Handle partial failures — if step 3 of 5 fails, what state is the system in?
- Use transactions for multi-step database operations

## Rules

- Read the codebase before writing. Changes that don't fit the existing patterns create maintenance burden.
- Write the simplest code that solves the problem correctly. Complexity is a cost, not a feature.
- If you're unsure about an approach, state the trade-off and let the user decide.
- Test your assumptions. If you think a function returns X, read it and verify.
- Don't leave broken windows. If you notice a bug while working on something else, fix it or flag it — don't ignore it.
