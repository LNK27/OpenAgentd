"""Single source of truth for the LLM provider catalog.

Both ``openagentd init`` (the CLI) and ``/api/settings/providers`` (the
desktop/web UI) consume this catalog. Adding a new provider means one
entry here plus a new ``case`` branch in
:func:`app.agent.providers.factory.build_provider`.

The catalog is intentionally a plain dict with one row per provider —
NOT a class hierarchy — because the data shape is uniform and the
frontend consumes it as JSON.
"""

from __future__ import annotations

from typing import Literal, TypedDict

ProviderKind = Literal["api_key", "oauth", "local", "cloud_creds"]


class ProviderEntry(TypedDict, total=False):
    """One provider's metadata.

    ``kind`` decides how the UI collects credentials:

    - ``api_key`` — single text input for ``env_var``.
    - ``oauth`` — browser/device flow handled by
      :mod:`app.cli.commands.auth`. Surfaces a "Connect" button.
    - ``local`` — no credentials needed (e.g. Ollama daemon on
      127.0.0.1). UI shows a connection status instead of inputs.
    - ``cloud_creds`` — needs more than one field (e.g. Vertex AI:
      project + location + gcloud auth). UI renders the field list
      from ``env_vars``.

    ``default_models`` is the curated fallback list the UI shows when live
    provider model discovery is unavailable.
    """

    id: str
    label: str
    description: str
    kind: ProviderKind
    env_var: str  # primary env var for api_key providers
    env_vars: list[str]  # multi-field providers (vertexai)
    default_models: list[str]
    oauth_command: str  # CLI fallback hint for oauth providers
    docs_url: str  # link to provider's API key dashboard


_CATALOG: list[ProviderEntry] = [
    {
        "id": "googlegenai",
        "label": "Google Gemini",
        "description": "Google AI Studio — free tier available.",
        "kind": "api_key",
        "env_var": "GOOGLE_API_KEY",
        "default_models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ],
        "docs_url": "https://aistudio.google.com/apikey",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "description": "GPT-5.x, GPT-4.1, etc.",
        "kind": "api_key",
        "env_var": "OPENAI_API_KEY",
        "default_models": [
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-pro",
            "gpt-5",
            "gpt-5-mini",
            "gpt-4.1",
        ],
        "docs_url": "https://platform.openai.com/api-keys",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "description": "Many models, free tiers available.",
        "kind": "api_key",
        "env_var": "OPENROUTER_API_KEY",
        "default_models": [
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.4",
            "google/gemini-3-flash-preview",
            "x-ai/grok-4",
            "qwen/qwen3-coder-plus",
            "deepseek/deepseek-v4",
            "meta-llama/llama-4-maverick:free",
        ],
        "docs_url": "https://openrouter.ai/keys",
    },
    {
        "id": "zai",
        "label": "Z.AI / GLM",
        "description": "Z.AI's GLM-5 family.",
        "kind": "api_key",
        "env_var": "ZAI_API_KEY",
        "default_models": [
            "glm-5",
            "glm-5.1",
            "glm-5-turbo",
            "glm-5v-turbo",
            "glm-4.7",
            "glm-4.6v",
        ],
        "docs_url": "https://z.ai/manage-apikey/apikey-list",
    },
    {
        "id": "nvidia",
        "label": "NVIDIA NIM",
        "description": "NVIDIA-hosted open models.",
        "kind": "api_key",
        "env_var": "NVIDIA_API_KEY",
        "default_models": [
            "deepseek-ai/deepseek-v3.1",
            "meta/llama-4-maverick-17b-128e-instruct",
            "qwen/qwen3-coder-480b-a35b-instruct",
            "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        ],
        "docs_url": "https://build.nvidia.com",
    },
    {
        "id": "xai",
        "label": "xAI Grok",
        "description": "xAI's Grok family.",
        "kind": "api_key",
        "env_var": "XAI_API_KEY",
        # grok-4, grok-4-fast, grok-code-fast-1 retire 2026-05-15 — they
        # redirect to grok-4.3 in the meantime. See:
        # https://docs.x.ai/docs/models
        "default_models": ["grok-4.3", "grok-4", "grok-4-fast"],
        "docs_url": "https://console.x.ai",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "description": "DeepSeek's direct API.",
        "kind": "api_key",
        "env_var": "DEEPSEEK_API_KEY",
        "default_models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-r1"],
        "docs_url": "https://platform.deepseek.com/api_keys",
    },
    {
        "id": "router9",
        "label": "9Router",
        "description": "Local proxy aggregating 40+ providers.",
        "kind": "api_key",
        "env_var": "ROUTER9_API_KEY",
        "default_models": [
            "cc/claude-sonnet-4-5-20250929",
            "cc/claude-opus-4-6",
            "gh/gpt-5",
            "gh/claude-4.5-sonnet",
            "gc/gemini-3-flash-preview",
            "kr/claude-sonnet-4.5",
        ],
        "docs_url": "https://github.com/9router/9router",
    },
    {
        "id": "cliproxy",
        "label": "CLIProxyAPI",
        "description": "Local proxy for Gemini CLI / Codex / Claude Code OAuth.",
        "kind": "api_key",
        "env_var": "CLIPROXY_API_KEY",
        "default_models": [
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview",
            "gpt-5.2-codex",
            "claude-sonnet-4-5-20250929",
        ],
        "docs_url": "https://github.com/luispater/CLIProxyAPI",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "description": "Run models locally with the Ollama daemon.",
        "kind": "local",
        "env_var": "OLLAMA_API_KEY",
        "default_models": [
            "llama3.2",
            "qwen2.5-coder",
            "deepseek-r1",
            "gemma3",
            "mistral",
            "kimi-k2.6-cloud",
            "deepseek-v4-pro-cloud",
        ],
        "docs_url": "https://ollama.com/library",
    },
    {
        "id": "copilot",
        "label": "GitHub Copilot",
        "description": "Use your Copilot subscription — OAuth, no API key.",
        "kind": "oauth",
        "env_var": "",
        "default_models": [
            "gpt-5.4",
            "gpt-5.4-mini",
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gemini-3.1-pro-preview",
        ],
        "oauth_command": "openagentd auth copilot",
        "docs_url": "https://github.com/features/copilot",
    },
    {
        "id": "codex",
        "label": "OpenAI Codex",
        "description": "Use your ChatGPT subscription via Codex OAuth.",
        "kind": "oauth",
        "env_var": "",
        "default_models": [
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.2",
            "gpt-5.1-codex",
        ],
        "oauth_command": "openagentd auth codex",
        "docs_url": "https://platform.openai.com/docs/codex",
    },
    {
        "id": "vertexai",
        "label": "Google Vertex AI",
        "description": "Google Cloud's enterprise-grade Gemini.",
        "kind": "cloud_creds",
        "env_var": "",
        "env_vars": ["GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"],
        "default_models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
        ],
        "docs_url": "https://cloud.google.com/vertex-ai/docs/start/cloud-environment",
    },
]


def all_providers() -> list[ProviderEntry]:
    """Return the full catalog in display order."""
    return list(_CATALOG)


def find(provider_id: str) -> ProviderEntry | None:
    """Return one entry by ``id`` or None if not in the catalog."""
    for entry in _CATALOG:
        if entry["id"] == provider_id:
            return entry
    return None


# Exported so the CLI and the seed installer can use the same set of
# env-var names without duplicating the mapping.
PROVIDER_KEY_VAR: dict[str, str] = {
    entry["id"]: entry["env_var"] for entry in _CATALOG if entry.get("env_var")
}
