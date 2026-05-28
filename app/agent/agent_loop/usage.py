from __future__ import annotations

from typing import Any

from app.agent.providers.model_metadata import get_model_cost
from app.agent.schemas.chat import Usage


def usage_to_dict(usage: Usage, model_id: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": usage.prompt_tokens,
        "output": usage.completion_tokens,
    }
    if usage.cached_tokens is not None:
        result["cache"] = usage.cached_tokens
    if usage.thoughts_tokens is not None:
        result["thoughts"] = usage.thoughts_tokens
    if usage.tool_use_tokens is not None:
        result["tool_use"] = usage.tool_use_tokens

    cost = _estimate_cost(usage, model_id)
    if cost:
        result["cost"] = cost
    return result


def _estimate_cost(usage: Usage, model_id: str | None) -> dict[str, float] | None:
    prices = get_model_cost(model_id)
    components: dict[str, float] = {}
    cached_tokens = usage.cached_tokens or 0

    if prices.cache_read is not None and cached_tokens > 0:
        components["cache_read_usd"] = cached_tokens * prices.cache_read / 1_000_000
        input_tokens = max(usage.prompt_tokens - cached_tokens, 0)
    else:
        input_tokens = usage.prompt_tokens

    if prices.input is not None and input_tokens > 0:
        components["input_usd"] = input_tokens * prices.input / 1_000_000
    if prices.output is not None and usage.completion_tokens > 0:
        components["output_usd"] = usage.completion_tokens * prices.output / 1_000_000

    if not components:
        return None
    return {"estimated_usd": sum(components.values()), **components}
