---
title: LLM Providers
description: Every provider registered in build_provider — keys, model IDs, vision defaults, OAuth flows.
status: stable
updated: 2026-05-21
---

# LLM Providers

**Sources:** `app/agent/providers/factory.py`, `app/agent/providers/catalog.py`, `app/agent/providers/plugin_registry.py`, `app/api/routes/settings.py`, `app/agent/providers/capabilities.py`, `app/agent/providers/model_metadata.py`

A model is selected by setting `model: <prefix>:<model-id>` in an agent's `.md` frontmatter. The prefix selects the provider; the rest is passed verbatim to that provider's API.

## Setup paths

- **Desktop/web UI:** open **Settings → Providers**. First launch creates the config/cache/state/data/workspace roots, `{OPENAGENTD_CONFIG_DIR}/plugins`, and default editable agents with a placeholder model. Packaged installs download those defaults from the GitHub release seed bundle. API-key providers write to `{OPENAGENTD_CONFIG_DIR}/.env`; OAuth providers use the in-app flow and store tokens under `{OPENAGENTD_CACHE_DIR}`.
- **CLI/server:** run `openagentd init` for first setup, or `openagentd auth copilot|codex` for OAuth-only providers.

Provider setup replaces the seeded placeholder model without overwriting existing user-edited files.

## Registered prefixes

Built-ins are resolved in `app/agent/providers/factory.py`; provider plugins are resolved from `{OPENAGENTD_CONFIG_DIR}/plugins/` after built-ins.

| Prefix | Auth | Notes |
|--------|------|-------|
| `anthropic` | `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_BASE_URL`) | Built-in Anthropic Messages API support. OAuth Claude Pro/Max access remains plugin-based. |
| `googlegenai` | `GOOGLE_API_KEY` | Google Gemini Developer API. |
| `vertexai` | `VERTEXAI_API_KEY` *or* ADC + `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | Vertex AI (express or normal mode). |
| `zai` | `ZAI_API_KEY` | ZAI / GLM. |
| `openai` | `OPENAI_API_KEY` | Chat Completions by default; `thinking_level` auto-routes to the Responses API. |
| `openrouter` | `OPENROUTER_API_KEY` | OpenRouter — any catalog model. |
| `nvidia` | `NVIDIA_API_KEY` | [NVIDIA NIM](https://build.nvidia.com/models). |
| `xai` | `XAI_API_KEY` | xAI Grok. |
| `deepseek` | `DEEPSEEK_API_KEY` | DeepSeek (OpenAI-compatible). |
| `bedrock` | AWS creds (env / profile / instance) | Converse API across all Bedrock model families. |
| `copilot` | `openagentd auth copilot` | GitHub Copilot OAuth (device flow). |
| `codex` | `openagentd auth codex` | OpenAI Codex via ChatGPT subscription. The UI tries device-code auth first, then falls back to browser PKCE when a workspace disables device-code auth. CLI uses browser PKCE by default; `--device` is available for headless setup. |
| `router9` | `ROUTER9_API_KEY` (+ optional `ROUTER9_BASE_URL`) | Local [9Router](https://github.com/decolua/9router) proxy. |
| `cliproxy` | `CLIPROXY_API_KEY` (+ optional `CLIPROXY_BASE_URL`) | Local [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) proxy. |
| `ollama` | `OLLAMA_API_KEY` (optional; daemon ignores auth) | Local [Ollama](https://docs.ollama.com/api/openai) at `http://localhost:11434/v1`. |

The model id after the prefix is passed **verbatim** to the upstream. The Settings model picker filters provider listings to agent-usable text-chat models, so generation-only models such as `veo-*`, `imagen-*`, image-preview, embeddings, and TTS models are hidden.

## Provider plugins

Drop-in provider plugins live in `{OPENAGENTD_CONFIG_DIR}/plugins/` and export a `ProviderPlugin` named `provider`. They can:

- appear in **Settings → Providers** with declared credential fields;
- save credentials to `{OPENAGENTD_CONFIG_DIR}/.env`;
- store provider-owned OAuth tokens under `{OPENAGENTD_CACHE_DIR}/provider-plugins/<provider-id>/`;
- provide model discovery and a factory returning `LLMProviderBase`.

The same directory can also contain agent hook plugins. Files that export
`provider = ProviderPlugin(...)` are handled by the provider registry and are
skipped by the agent hook loader.

OAuth plugins can emit a `code_required` event; the UI then shows a paste field and posts the code to `/api/auth/{provider}/callback`.

If an OAuth refresh token is rejected by the upstream provider, the provider should raise `ProviderAuthenticationError`. Team execution maps that to the same actionable `agent_not_configured` stream event as an unconfigured model, so the UI can ask the user to reconnect the provider instead of surfacing an internal stack trace.

## Capability detection

Each model's input/output capabilities (vision, document text, audio, video, etc.) are resolved by `get_capabilities(model_id)` in `capabilities.py`:

1. Longest prefix match (e.g. `openai:`) → use that prefix's default.
2. Global default → text-only.

There are no per-model overrides and no name-substring heuristics. Edge cases (e.g. attaching an image to a text-only model under a vision prefix, or vice versa) surface as a provider-side error on first use. See `documents/techdebts/model-capabilities-registry.md` for the long-term direction.

## Model metadata

Non-modality model metadata lives in `app/agent/providers/model_metadata.yaml` and is resolved through `model_metadata.py`. It currently tracks token limits and advertised `thinking_level` values:

```yaml
"openai:gpt-5":
  limits: { context_length: 272000, max_completion_tokens: 128000 }
  thinking: { levels: [minimal, low, medium, high] }
```

`thinking.levels` is descriptive metadata for callers such as settings UIs or validation layers. Runtime provider behavior still treats `thinking_level: none`/`off` as disable/default even when `none` is not listed for a model.

## Provider notes

### `googlegenai` / `vertexai`

Standard Gemini APIs. `_sanitize_schema()` strips JSON-Schema fields Gemini doesn't accept (`discriminator`, `const`, `exclusiveMinimum`, `additionalProperties`). New unsupported fields can be added to `_UNSUPPORTED_SCHEMA_KEYS` in `googlegenai.py` — see [`troubleshooting.md`](../troubleshooting.md).

### `openai`

Chat Completions by default. Setting any non-`none` `thinking_level` automatically routes through the **Responses API** (`/v1/responses`) because Chat Completions doesn't accept `reasoning_effort` alongside function tools. Override via `model_kwargs.responses_api: true/false`.

When routed to `/v1/responses`, `temperature` and `top_p` are silently ignored (the API doesn't accept them); `max_tokens` maps to `max_output_tokens`.

### `anthropic`

Uses Anthropic's Messages API at `https://api.anthropic.com/v1/messages`. API-key support is built in and configured with `ANTHROPIC_API_KEY`; set `ANTHROPIC_BASE_URL` only for compatible gateways. Claude Pro/Max OAuth flows stay out of core and should be implemented as provider plugins such as `anthropic-oauth`.

`thinking_level` maps to Anthropic `thinking` controls on supported Claude models. Sampling fields are omitted for newer Claude 4.5+ families that reject legacy sampling parameters.

### `codex`

Uses your **ChatGPT Plus/Pro subscription** to access OpenAI models via `https://chatgpt.com/backend-api/codex/responses`. The endpoint is Responses API only — `temperature` and `top_p` are silently ignored, `thinking_level` maps to `reasoning.effort`. The same OAuth token also powers `generate_image` when `multimodal.yaml` sets `image.model: codex:<chat-model>`.

### `copilot`

GitHub Copilot OAuth — requires an active Copilot subscription. Models include `copilot:gpt-…`, `copilot:claude-…`, etc. (see Copilot's catalog).

### `bedrock`

Uses the **Converse API** (`boto3 bedrock-runtime`). Auth resolves in priority order:

1. Explicit `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`.
2. Named profile via `AWS_BEDROCK_PROFILE`.
3. Standard boto3 credential chain (instance profile, IAM role, etc.).

Region: `AWS_BEDROCK_REGION` → `AWS_DEFAULT_REGION` → `us-east-1`.

Prefer `global.*` model IDs for higher availability. The provider uses `asyncio.to_thread` to wrap boto3's synchronous calls — `aiobotocore` is not used because it lacks Bedrock's `converse_stream` event-stream format.

Smoke tests (no server required):

```bash
uv run python -m manual.try_providers.try_bedrock --simple
uv run python -m manual.try_providers.try_bedrock --tools
```

### `router9` / `cliproxy`

Both talk to a **locally-running OpenAI-compatible proxy** that fans out to many upstream models. Set the API key (and optionally override the default port via `*_BASE_URL`).

| Provider | Upstream | Default base URL |
|----------|----------|------------------|
| `router9` | 9Router — Node.js dashboard, 40+ providers, quota tracking | `http://localhost:20128/v1` |
| `cliproxy` | CLIProxyAPI — Go proxy wrapping Gemini CLI / ChatGPT Codex / Claude Code OAuth | `http://localhost:8317/v1` |

The model id after the prefix is passed verbatim to the proxy — see the upstream dashboard / `/v1/models` for the live catalog. If `cliproxy` is run without auth, any non-empty `CLIPROXY_API_KEY` value works (the header is required by the OpenAI client).

### `ollama`

Talks to the local Ollama daemon over its OpenAI-compatible API. The daemon ignores auth, so `OLLAMA_API_KEY` defaults to unset. The provider supplies an internal placeholder only when calling the OpenAI SDK.

```bash
ollama serve                # daemon (usually already running)
ollama pull llama3.2        # pull any model
```

**Cloud models.** Ollama Cloud runs *through* the same local daemon — there is no separate HTTPS endpoint. After running `ollama signin` once, any model name with the `-cloud` suffix is transparently routed to [ollama.com](https://ollama.com/search?c=cloud). Use the exact name `ollama list` shows.

**Remote daemon.** Point at a daemon on another machine via `OLLAMA_BASE_URL`.

**Capability defaults:** vision is `false` for the `ollama:` prefix. If you run a vision-capable model (e.g. `llava`), attach images via the chat UI and accept that the upload gate is conservative for the whole prefix.

## Thinking (`thinking_level`)

Enables extended reasoning on supporting models.

| Value | Behaviour |
|-------|-----------|
| `none` (default) | Thinking disabled. |
| `low` | Lightweight reasoning pass. |
| `medium` | Balanced reasoning. |
| `high` | Maximum reasoning effort. |

Mapping varies per provider. Some use reasoning effort fields, some use provider-specific thinking objects, and non-reasoning models ignore the field.

## Fallback model

When the primary model fails with retryable errors (429, 5xx, timeouts), the agent can automatically switch to a fallback model.

```yaml
model: zai:glm-5v-turbo             # primary
fallback_model: copilot:gpt-5-mini  # used after retry exhaustion or quota 429s
```

- Primary is retried 5× with exponential backoff for transient failures.
- Quota-style 429s, such as usage-limit or insufficient-balance responses, skip retries and switch to fallback immediately.
- On the last transient attempt, no sleep — switches to fallback immediately.
- Fallback gets its own 5-retry budget with the same backoff.
- Non-retryable errors (400, 401, 403) are raised immediately — no fallback.
- If unset, the existing retry-only behaviour is unchanged.

See [`agent/loop.md#retry-logic-and-fallback-model`](../agent/loop.md#retry-logic-and-fallback-model).
