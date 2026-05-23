"""DeepSeek provider — OpenAI-compatible API.

Thin wrapper around ``OpenAIProvider`` that points at the DeepSeek
inference endpoint and reads ``DEEPSEEK_API_KEY`` from settings or
environment.

Endpoint:  https://api.deepseek.com/v1
Auth:      Bearer {DEEPSEEK_API_KEY}
Docs:      https://api-docs.deepseek.com/

Models:
    deepseek-v4-flash  — fast general-purpose chat
    deepseek-v4-pro    — higher-quality variant

Reasoning-model outputs via ``reasoning_content`` are already supported
by the OpenAI schema layer (see ``app/agent/providers/openai/schemas.py``),
so no extra wiring is required here.

Token resolution order:
    1. ``Settings.DEEPSEEK_API_KEY`` (from ``.env`` or environment)
    2. ``DEEPSEEK_API_KEY`` environment variable

Usage::

    model: deepseek:deepseek-v4-flash
    model: deepseek:deepseek-v4-pro
"""

from __future__ import annotations

from typing import Any

from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"


class _DeepSeekCompletionsHandler(CompletionsHandler):
    """DeepSeek's /chat/completions accepts ``max_tokens`` only.

    The shared OpenAI handler defaults to ``max_completion_tokens`` (the
    field name OpenAI's reasoning models require since 2024-09).  As of
    2026-Q2 the DeepSeek API reference at
    https://api-docs.deepseek.com/api/create-chat-completion documents
    only ``max_tokens`` — sending ``max_completion_tokens`` is silently
    dropped, causing unbounded responses.  Pin this subclass to the
    legacy field name until DeepSeek catches up.
    """

    uses_max_completion_tokens = False


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider (OpenAI-compatible).

    Delegates entirely to ``OpenAIProvider`` with the DeepSeek base URL.
    Vision is not supported by current DeepSeek models.

    Args:
        api_key: DeepSeek API key from https://platform.deepseek.com.
        model: Model name, e.g. ``"deepseek-v4-flash"``, ``"deepseek-v4-pro"``.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=DEEPSEEK_API_BASE,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _DeepSeekCompletionsHandler(model, base_url, headers)
