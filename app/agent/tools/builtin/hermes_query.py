"""hermes_query tool -- read-only recall from Hermes."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Annotated

from pydantic import Field

from app.agent.tools.builtin._observability import (
    SECOND_BRAIN_ERROR,
    SECOND_BRAIN_OK,
    record_second_brain_tool_observation,
)
from app.agent.tools.registry import Tool
from app.services.hermes import (
    HermesConnectionError,
    HermesQueryRequest,
    HermesQueryResult,
    HermesSchemaError,
    HermesTimeoutError,
    HermesUnavailableError,
    query_recall,
)


async def _hermes_query(
    query: Annotated[
        str,
        Field(description="The read-only memory question to ask Hermes."),
    ],
    context: Annotated[
        str,
        Field(
            description=(
                "Optional context string for Hermes. It will be clamped by the "
                "Hermes adapter before transport."
            )
        ),
    ] = "",
    max_results: Annotated[
        int,
        Field(description="Maximum recall items to request, clamped to 1..20."),
    ] = 5,
) -> str:
    """Ask Hermes for read-only recall/query results without writing.

    Use this to retrieve or synthesize memory from Hermes. This tool never
    writes to the Obsidian vault, never enqueues approvals, and never drafts
    skills. For new-note proposals, use hermes_propose instead.
    """
    start = time.perf_counter()
    attrs = {
        "hermes.query_length": len(query or ""),
        "hermes.context_length": len(context or ""),
        "hermes.max_results": max_results,
    }
    try:
        result = await query_recall(
            HermesQueryRequest(
                query=query,
                context=context,
                max_results=max_results,
            )
        )
    except HermesUnavailableError as exc:
        _record("unavailable", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector unavailable: {exc}"
    except HermesTimeoutError as exc:
        _record("timeout", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector timed out: {exc}"
    except HermesConnectionError as exc:
        _record("connection_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector connection failed: {exc}"
    except HermesSchemaError as exc:
        _record("schema_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector schema error: {exc}"

    _record(
        "answered",
        SECOND_BRAIN_OK,
        start,
        {**attrs, "hermes.result_count": len(result.items)},
    )
    return _format_query_result(result)


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="hermes_query",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


def _format_query_result(result: HermesQueryResult) -> str:
    payload = {
        "answer": result.answer,
        "warnings": result.warnings,
        "model_info": result.model_info,
        "items": [
            {
                "path": item.path,
                "title": item.title,
                "excerpt": item.excerpt,
                "score": item.score,
                "tags": item.tags,
            }
            for item in result.items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


hermes_query = Tool(
    _hermes_query,
    name="hermes_query",
    description=(
        "Ask the Hermes sidecar for read-only memory recall/query results. "
        "This tool never writes to the vault, never enqueues approvals, and "
        "does not draft skills."
    ),
)
