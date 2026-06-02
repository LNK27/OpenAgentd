"""vault_search tool -- search the Obsidian vault."""

from __future__ import annotations

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
from app.services.vault_gatekeeper import VaultPathError
from app.services.vault_search import search_notes


async def _vault_search(
    query: Annotated[
        str,
        Field(description="Search query. Empty string lists notes by folder/tags."),
    ] = "",
    folder: Annotated[
        str | None,
        Field(description="Optional standard vault folder filter."),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Optional tags to filter by. All requested tags must match."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of results to return, clamped to 1..20."),
    ] = 5,
) -> str:
    """Search Obsidian vault notes by keyword, folder, and tags."""
    start = time.perf_counter()
    attrs = _attrs(query=query, folder=folder, tags=tags, limit=limit)
    try:
        results = await search_notes(query, folder=folder, tags=tags, limit=limit)
    except VaultPathError as exc:
        _record("invalid_path", SECOND_BRAIN_ERROR, start, attrs)
        return str(exc)

    if not results:
        _record(
            "no_results",
            SECOND_BRAIN_OK,
            start,
            {**attrs, "vault.result_count": 0},
        )
        return "No notes found matching your query."

    _record(
        "results",
        SECOND_BRAIN_OK,
        start,
        {**attrs, "vault.result_count": len(results)},
    )
    parts = [f"Vault search results for: {query or '(browse)'}"]
    for note, score, snippet in results:
        tag_text = ", ".join(note.tags) if note.tags else "(none)"
        parts.append(
            "\n".join(
                [
                    f"Path: {note.folder}/{note.slug}",
                    f"Title: {note.title}",
                    f"Type: {note.note_type}",
                    f"Tags: {tag_text}",
                    f"Score: {score:.2f}",
                    f"Snippet: {snippet}",
                ]
            )
        )
    return "\n\n".join(parts)


def _attrs(
    *,
    query: str,
    folder: str | None,
    tags: list[str] | None,
    limit: int,
) -> dict[str, object]:
    attrs: dict[str, object] = {
        "vault.query_length": len(query or ""),
        "vault.tags_count": len(tags or []),
        "vault.limit": limit,
    }
    if folder is not None:
        attrs["vault.folder"] = folder
    return attrs


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="vault_search",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


vault_search = Tool(
    _vault_search,
    name="vault_search",
    description=(
        "Search the Obsidian vault by keyword, folder, or tags. Returns note "
        "paths, metadata, relevance scores, and short snippets."
    ),
)
