from __future__ import annotations

from app.agent.providers.model_metadata import get_model_limits, get_model_metadata


def test_get_model_limits_returns_known_limits() -> None:
    limits = get_model_limits("openai:gpt-5")

    assert limits.context_length == 272000
    assert limits.max_completion_tokens == 128000


def test_get_model_metadata_is_case_insensitive() -> None:
    metadata = get_model_metadata("OPENAI:GPT-5")

    assert metadata.limits.context_length == 272000


def test_get_model_limits_unknown_model_returns_none_limits() -> None:
    limits = get_model_limits("unknown:model")

    assert limits.context_length is None
    assert limits.max_completion_tokens is None
