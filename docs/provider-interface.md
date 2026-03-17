# Provider Interface

## Scope

DeathStar v1 supports exactly three AI providers:

- OpenAI
- Anthropic
- Google

The rest of the system should treat provider adapters as interchangeable text-generation backends.

## Adapter Contract

Provider adapters implement one job:

- accept a normalized prompt request
- call the provider
- return normalized text, model metadata, usage, and a provider response ID
- map provider-specific failures into common error codes

The higher-level workflows live above the adapter layer.

That means:

- prompt workflows build a user prompt
- patch workflows build a patch-generation prompt
- PR workflows build a summary-generation prompt
- review workflows build an independent review prompt

Each workflow still calls the same provider adapter interface.

## Interface Shape

The Python interface is effectively:

```python
async def generate_text(
    *,
    prompt: str,
    model: str | None,
    system: str | None,
    timeout_seconds: int,
) -> ProviderResult:
    ...
```

`ProviderResult` contains:

- `text`
- `model`
- `usage`
- `remote_response_id`

## Normalized Error Codes

- `auth_error`
  Provider or integration rejected credentials
- `provider_not_configured`
  Required provider API key is missing remotely
- `integration_not_configured`
  Optional integration, such as GitHub PR automation, is missing
- `invalid_request`
  The request shape or remote workspace state is not valid
- `invalid_provider_output`
  The provider returned output that DeathStar could not safely use
- `rate_limited`
  The upstream asked the caller to slow down
- `upstream_timeout`
  The provider timed out
- `upstream_unavailable`
  The provider or integration is temporarily unavailable
- `backup_not_found`
  Requested backup archive was not found
- `internal_error`
  Unexpected internal failure

## Why The Contract Is Text-First

A text-first adapter keeps the provider abstraction stable.

- provider-specific chat or response schemas stay inside the adapter
- workflows can evolve without changing the CLI
- adding a future provider mostly means implementing one adapter

## Patch Workflow Rules

The patch workflow relies on a strict provider output contract:

- return unified diff only
- use repo-relative paths
- no markdown fences
- no prose

If the provider does not follow that contract, DeathStar returns `invalid_provider_output` instead of attempting an unsafe write.

## PR And Review Independence

PR drafting and review each run as their own provider calls with fresh inputs derived from git state.

They do not reuse:

- the implementation prompt
- hidden chat history
- prior agent reasoning

That is the mechanism that gives the PR writer and reviewer their own context over the actual diff instead of over a conversation transcript.
