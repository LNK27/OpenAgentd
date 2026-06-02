"""Observability helpers for Second Brain builtin tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.metrics import (
    SECOND_BRAIN_TOOL_CALLS,
    SECOND_BRAIN_TOOL_DURATION,
)

SECOND_BRAIN_OK = "ok"
SECOND_BRAIN_ERROR = "error"


def record_second_brain_tool_observation(
    *,
    tool: str,
    outcome: str,
    status: str,
    duration_seconds: float,
    attributes: Mapping[str, object] | None = None,
    span=None,  # noqa: ANN001 - tests can pass a small span stub.
) -> None:
    """Annotate the current tool span and record low-cardinality metrics."""
    resolved_status = (
        SECOND_BRAIN_ERROR if status == SECOND_BRAIN_ERROR else SECOND_BRAIN_OK
    )
    resolved_span = span if span is not None else trace.get_current_span()

    resolved_span.set_attribute("openagentd.second_brain.tool", tool)
    resolved_span.set_attribute("openagentd.second_brain.outcome", outcome)
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        resolved_span.set_attribute(key, cast(Any, value))
    if resolved_status == SECOND_BRAIN_ERROR:
        resolved_span.set_status(Status(StatusCode.ERROR, outcome))

    SECOND_BRAIN_TOOL_CALLS.labels(tool=tool, status=resolved_status).inc()
    SECOND_BRAIN_TOOL_DURATION.labels(tool=tool, status=resolved_status).observe(
        max(0.0, float(duration_seconds))
    )
