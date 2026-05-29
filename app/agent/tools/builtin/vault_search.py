"""vault_search tool -- search the Obsidian vault."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

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
    try:
        results = await search_notes(query, folder=folder, tags=tags, limit=limit)
    except VaultPathError as exc:
        return str(exc)

    if not results:
        return "No notes found matching your query."

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


vault_search = Tool(
    _vault_search,
    name="vault_search",
    description=(
        "Search the Obsidian vault by keyword, folder, or tags. Returns note "
        "paths, metadata, relevance scores, and short snippets."
    ),
)
