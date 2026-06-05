"""9Router provider — OpenAI-compatible Chat Completions endpoint."""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import OpenAIProvider


class Router9Provider(OpenAIProvider):
    """9Router provider.

    9Router exposes an OpenAI-compatible ``/chat/completions`` endpoint, but
    not OpenAI's ``/responses`` endpoint. Always route to chat completions,
    even when ``thinking_level`` or ``responses_api`` is set by session or
    agent config.
    """

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _use_responses_for(self, model_kwargs: dict[str, Any]) -> bool:
        return False
