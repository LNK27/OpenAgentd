"""Model metadata resolution.

Looks up per-model limits and other non-modality metadata for a fully-qualified
``provider:model`` string against a curated YAML registry shipped inside the
wheel.

This module intentionally stays separate from ``capabilities.py`` for now:
capabilities remain the source of truth for input/output modality gates, while
this registry carries operational limits such as context window and maximum
completion tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml
from loguru import logger


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for one model.

    ``None`` means unknown, not unlimited.
    """

    context_length: int | None = None
    max_completion_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "context_length": self.context_length,
            "max_completion_tokens": self.max_completion_tokens,
        }


@dataclass(frozen=True)
class ModelThinking:
    """Reasoning/thinking controls supported by one model."""

    levels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {"levels": list(self.levels)}


@dataclass(frozen=True)
class ModelMetadata:
    """Non-modality metadata for one ``provider:model`` pair."""

    limits: ModelLimits = ModelLimits()
    thinking: ModelThinking = ModelThinking()

    def to_dict(self) -> dict[str, dict[str, int | None] | dict[str, list[str]]]:
        return {"limits": self.limits.to_dict(), "thinking": self.thinking.to_dict()}


_DEFAULT = ModelMetadata()


def _positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{field}` must be a positive integer")
    if value <= 0:
        raise ValueError(f"`{field}` must be a positive integer")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"`{field}` must be a list of strings")
    return tuple(value)


def _merge_metadata(spec: dict[str, Any]) -> ModelMetadata:
    limits_spec = spec.get("limits") or {}
    thinking_spec = spec.get("thinking") or {}
    if not isinstance(limits_spec, dict):
        raise TypeError("`limits` must be a mapping")
    if not isinstance(thinking_spec, dict):
        raise TypeError("`thinking` must be a mapping")

    return ModelMetadata(
        limits=ModelLimits(
            context_length=_positive_int(
                limits_spec.get("context_length"), "limits.context_length"
            ),
            max_completion_tokens=_positive_int(
                limits_spec.get("max_completion_tokens"),
                "limits.max_completion_tokens",
            ),
        ),
        thinking=ModelThinking(
            levels=_string_tuple(thinking_spec.get("levels"), "thinking.levels")
        ),
    )


def _load_registry() -> dict[str, ModelMetadata]:
    resource = files("app.agent.providers").joinpath("model_metadata.yaml")
    raw = resource.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        logger.warning(
            "model_metadata.yaml did not parse to a mapping (got {}); ignoring",
            type(parsed).__name__,
        )
        return {}

    registry: dict[str, ModelMetadata] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            logger.warning(
                "model_metadata.yaml: skipping malformed entry key={!r}", key
            )
            continue
        try:
            registry[key.lower()] = _merge_metadata(value)
        except (TypeError, ValueError) as exc:
            logger.warning("model_metadata.yaml: skipping entry {!r} ({})", key, exc)
    logger.debug("model_metadata.yaml: loaded {} entries", len(registry))
    return registry


@lru_cache(maxsize=1)
def _registry() -> dict[str, ModelMetadata]:
    return _load_registry()


def get_model_metadata(model_id: str | None) -> ModelMetadata:
    """Return metadata for a fully-qualified ``provider:model`` string."""
    if not model_id:
        return _DEFAULT
    return _registry().get(model_id.lower(), _DEFAULT)


def get_model_limits(model_id: str | None) -> ModelLimits:
    """Return token limits for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).limits


def get_model_thinking_levels(model_id: str | None) -> tuple[str, ...]:
    """Return supported thinking levels for a fully-qualified model ID."""
    return get_model_metadata(model_id).thinking.levels
