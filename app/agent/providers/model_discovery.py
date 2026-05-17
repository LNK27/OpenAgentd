from __future__ import annotations

import os
from collections.abc import Mapping

import httpx
from loguru import logger

from app.agent.providers.catalog import ProviderEntry
from app.core.config import settings

TIMEOUT_S = 3.0


def _secret_value(value: object) -> str:
    if value is None:
        return ""
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return str(get_secret_value())
    return str(value)


def _resolve(overrides: Mapping[str, str] | None, name: str, default: str = "") -> str:
    """Look up a value: overrides → env → settings → default.

    Used to thread per-request credentials/base-URLs through discovery
    without mutating ``os.environ`` (which would leak to concurrent
    requests).
    """
    if overrides and name in overrides:
        return overrides[name]
    env_val = os.getenv(name)
    if env_val:
        return env_val
    setting_val = _secret_value(getattr(settings, name, None))
    return setting_val or default


async def _openai_compatible_models(
    *,
    provider_id: str,
    base_url: str,
    api_key: str,
) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    models = sorted(
        str(item["id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    logger.debug(
        "provider_models_discovered provider={} count={}", provider_id, len(models)
    )
    return models


async def _google_genai_models(overrides: Mapping[str, str] | None) -> list[str]:
    api_key = _resolve(overrides, "GOOGLE_API_KEY")
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("models", []) if isinstance(data, dict) else []
    models: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        methods = item.get("supportedGenerationMethods", [])
        if isinstance(name, str) and "generateContent" in methods:
            models.append(name.removeprefix("models/"))
    return sorted(models)


async def _copilot_models() -> list[str]:
    from app.agent.providers.copilot.oauth import CopilotOAuth

    oauth = CopilotOAuth.load()
    if oauth is None:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://api.githubcopilot.com/models",
            headers={
                "Authorization": f"Bearer {oauth.github_token.get_secret_value()}",
                "Accept": "application/json",
                "User-Agent": "openagentd/1.0.0",
            },
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    return sorted(
        str(item["id"])
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("model_picker_enabled", True)
    )


async def _codex_models() -> list[str]:
    from app.agent.providers.codex.oauth import CodexOAuth

    oauth = CodexOAuth.load()
    if oauth is None:
        return []
    if oauth.is_expired():
        oauth = oauth.refresh()
    headers = {
        "Authorization": f"Bearer {oauth.access_token.get_secret_value()}",
        "Content-Type": "application/json",
        "User-Agent": "openagentd/1.0.0",
        "originator": "openagentd",
    }
    if oauth.account_id:
        headers["ChatGPT-Account-Id"] = oauth.account_id
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://chatgpt.com/backend-api/codex/models",
            params={"client_version": "1.0.0"},
            headers=headers,
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("models", []) if isinstance(data, dict) else []
    return sorted(
        str(item["slug"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("slug"), str)
    )


async def _bedrock_models() -> list[str]:
    import boto3

    region = (
        settings.AWS_BEDROCK_REGION or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    )
    kwargs: dict[str, str] = {"region_name": region}
    if settings.AWS_BEDROCK_PROFILE:
        session = boto3.Session(profile_name=settings.AWS_BEDROCK_PROFILE)
        client = session.client("bedrock", **kwargs)
    else:
        client = boto3.client("bedrock", **kwargs)
    response = client.list_foundation_models(byOutputModality="TEXT")
    summaries = response.get("modelSummaries", [])
    return sorted(
        str(item["modelId"])
        for item in summaries
        if isinstance(item, dict) and isinstance(item.get("modelId"), str)
    )


async def discover_provider_models(
    entry: ProviderEntry,
    *,
    overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """Return live provider model IDs, or ``[]`` on failure / unsupported.

    ``overrides`` lets callers (e.g. the settings ``/models`` route) inject
    a candidate API key + base URL for a single request without mutating
    ``os.environ`` — which would leak to other concurrent requests.
    """
    provider_id = entry["id"]
    try:
        match provider_id:
            case "openai":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://api.openai.com/v1",
                    api_key=_resolve(overrides, "OPENAI_API_KEY"),
                )
            case "openrouter":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://openrouter.ai/api/v1",
                    api_key=_resolve(overrides, "OPENROUTER_API_KEY"),
                )
            case "nvidia":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://integrate.api.nvidia.com/v1",
                    api_key=_resolve(overrides, "NVIDIA_API_KEY"),
                )
            case "zai":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://api.z.ai/api/paas/v4",
                    api_key=_resolve(overrides, "ZAI_API_KEY"),
                )
            case "xai":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://api.x.ai/v1",
                    api_key=_resolve(overrides, "XAI_API_KEY"),
                )
            case "deepseek":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://api.deepseek.com/v1",
                    api_key=_resolve(overrides, "DEEPSEEK_API_KEY"),
                )
            case "router9":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url=_resolve(
                        overrides, "ROUTER9_BASE_URL", settings.ROUTER9_BASE_URL
                    ),
                    api_key=_resolve(overrides, "ROUTER9_API_KEY"),
                )
            case "cliproxy":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url=_resolve(
                        overrides, "CLIPROXY_BASE_URL", settings.CLIPROXY_BASE_URL
                    ),
                    api_key=_resolve(overrides, "CLIPROXY_API_KEY"),
                )
            case "ollama":
                return await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url=_resolve(
                        overrides, "OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL
                    ),
                    api_key=_resolve(overrides, "OLLAMA_API_KEY") or "ollama",
                )
            case "googlegenai":
                return await _google_genai_models(overrides)
            case "copilot":
                return await _copilot_models()
            case "codex":
                return await _codex_models()
            case "bedrock":
                return await _bedrock_models()
            case _:
                return []
    except Exception as exc:
        logger.info(
            "provider_models_unavailable provider={} error={}", provider_id, exc
        )
        return []
