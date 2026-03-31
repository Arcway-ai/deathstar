# Agent System

## Overview

The web UI chat pipeline is powered by the Claude Agent SDK. Each workflow mode runs a Claude agent session with different tool permissions, plugins, and turn limits. The agent handles tool calling, file access, and session continuity — the server translates SDK events into WebSocket messages for the frontend.

## Workflow Modes

| Mode | Tools | Turn Limit | Plugins |
|------|-------|------------|---------|
| Chat | Read, Glob, Grep, WebSearch, WebFetch | 30 | security-guidance |
| Code | Read, Write, Edit, Bash, Glob, Grep | Unlimited | security-guidance, deathstar-code, frontend-design |
| PR | Read, Write, Edit, Bash, Glob, Grep | Unlimited | security-guidance, deathstar-code, frontend-design, feature-dev |
| Review | Read, Glob, Grep, Bash, Agent | 50 | security-guidance, deathstar-review, code-review, pr-review-toolkit |
| Docs | Read, Write, Edit, Glob, Grep | 50 | security-guidance, deathstar-docs, frontend-design |
| Audit | Read, Glob, Grep, Bash | 50 | security-guidance, deathstar-audit |
| Plan | Read, Glob, Grep | 30 | security-guidance, deathstar-plan |

Code and PR modes have no turn limits — they run until the task is complete or the user interrupts.

## Session Lifecycle

1. **Connect**: Frontend opens a WebSocket to `/web/api/agent`.
2. **Start**: Client sends `start` with prompt, workflow, repo path, model, and optional `session_id` for resumption.
3. **Stream**: Server runs `claude_agent_sdk.query()` and translates events:
   - `AssistantMessage` with `TextBlock` → `delta` (streamed text)
   - `AssistantMessage` with `ToolUseBlock` → `progress` (tool name)
   - `ResultMessage` → `done` (final content, usage, cost, session_id)
4. **Resume**: The returned `session_id` can be passed back to continue the conversation.

## Context Injection

When a repo is selected, the server automatically injects into the system prompt:

- **CLAUDE.md**: Project instructions from the repo root (if present)
- **Branch**: Current git branch name
- **Recent commits**: Last N commit messages for context
- **File tree**: Repository file listing for navigation
- **Memory bank**: Previously saved useful responses for this repo (within a ~4K char budget)
- **Persona**: Selected persona system prompt (Frontend, Full-stack, Security, DevOps, Data, Architect)

## Plugin System

Plugins extend agent behavior per workflow mode:

- **Base plugins** (all modes): `security-guidance` — fires on write tools for security checks
- **Custom plugins**: `deathstar-code`, `deathstar-review`, `deathstar-docs`, `deathstar-audit`, `deathstar-plan`
- **Official plugins**: `code-review`, `pr-review-toolkit`, `frontend-design`, `feature-dev`

Plugins are discovered from:

1. `CLAUDE_PLUGIN_DIR` environment variable
2. `/opt/claude-plugins` (pre-installed in Docker image)
3. `~/.claude/plugins/marketplaces/claude-plugins-official/plugins` (local dev)
4. `/workspace/deathstar/.claude/plugins/marketplaces/claude-plugins-official/plugins` (container)

Missing plugins are auto-installed from the official repo or the local `plugins/` directory on first use.

## Agent Controls

The frontend provides:

- **Send**: Submit a prompt to start or continue a conversation
- **Stop**: Interrupt the running agent session
- **Poke**: Send a "continue" nudge when the stream appears stalled
- **Permission prompts**: Agent tool calls that need approval surface as inline permission requests

## Error Handling

- Agent errors yield an `error` SSE event with code and message
- The frontend displays errors inline in the chat
- Session state is preserved — the conversation can be resumed after errors
- Cost and usage are tracked per message in the `done` event

## Legacy CLI Workflows

The CLI `deathstar run` command uses a separate multi-provider layer (OpenAI, Anthropic, Google) with a text-first adapter pattern. This is independent from the Agent SDK pipeline and is retained for scripted/headless use cases. See `server/deathstar_server/services/workflow.py` and `server/deathstar_server/providers/`.
