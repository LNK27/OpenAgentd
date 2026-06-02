"""vault_read tool -- read one Obsidian vault note."""

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
from app.services.markdown_text import (
    VaultFrontmatterParseError,
    split_vault_note_frontmatter,
)
from app.services.vault_search import read_note

_MIN_CHARS = 1000
_MAX_CHARS = 50000
_MALFORMED_WARNING = (
    "[Warning: Note has malformed frontmatter. Showing raw content instead.]"
)


async def _vault_read(
    folder: Annotated[str, Field(description="Standard vault folder.")],
    slug: Annotated[str, Field(description="Note filename stem without .md suffix.")],
    include_frontmatter: Annotated[
        bool,
        Field(description="Whether to include leading YAML frontmatter."),
    ] = True,
    max_chars: Annotated[
        int,
        Field(description="Maximum characters to return, clamped to 1000..50000."),
    ] = 12000,
) -> str:
    """Read one Obsidian vault note by folder and slug."""
    start = time.perf_counter()
    attrs = {
        "vault.folder": folder,
        "vault.path": f"{folder}/{slug}.md",
        "vault.include_frontmatter": include_frontmatter,
        "vault.max_chars": _clamp_chars(max_chars),
    }
    try:
        raw = await read_note(folder, slug)
    except FileNotFoundError:
        _record("not_found", SECOND_BRAIN_ERROR, start, attrs)
        return f"Note not found at vault/{folder}/{slug}.md"
    except ValueError as exc:
        _record("invalid_path", SECOND_BRAIN_ERROR, start, attrs)
        return str(exc)

    outcome = "read"
    content = raw
    if not include_frontmatter:
        try:
            content = split_vault_note_frontmatter(raw).body
        except VaultFrontmatterParseError:
            outcome = "malformed_frontmatter"
            content = f"{_MALFORMED_WARNING}\n\n{raw}"
    max_chars_clamped = _clamp_chars(max_chars)
    truncated = len(content) > max_chars_clamped
    result = _truncate(content, max_chars_clamped)
    _record(
        outcome,
        SECOND_BRAIN_OK,
        start,
        {
            **attrs,
            "vault.result_length": len(result),
            "vault.truncated": truncated,
        },
    )
    return result


def _clamp_chars(max_chars: int) -> int:
    return max(_MIN_CHARS, min(int(max_chars), _MAX_CHARS))


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return f"{content[:max_chars]}\n\n[truncated at {max_chars} characters]"


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="vault_read",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


vault_read = Tool(
    _vault_read,
    name="vault_read",
    description=(
        "Read a specific Obsidian vault note by folder and slug. Use after "
        "vault_search when full note content is needed."
    ),
)
