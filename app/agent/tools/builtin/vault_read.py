"""vault_read tool -- read one Obsidian vault note."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

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
    try:
        raw = await read_note(folder, slug)
    except FileNotFoundError:
        return f"Note not found at vault/{folder}/{slug}.md"
    except ValueError as exc:
        return str(exc)

    content = raw
    if not include_frontmatter:
        try:
            content = split_vault_note_frontmatter(raw).body
        except VaultFrontmatterParseError:
            content = f"{_MALFORMED_WARNING}\n\n{raw}"
    return _truncate(content, _clamp_chars(max_chars))


def _clamp_chars(max_chars: int) -> int:
    return max(_MIN_CHARS, min(int(max_chars), _MAX_CHARS))


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return f"{content[:max_chars]}\n\n[truncated at {max_chars} characters]"


vault_read = Tool(
    _vault_read,
    name="vault_read",
    description=(
        "Read a specific Obsidian vault note by folder and slug. Use after "
        "vault_search when full note content is needed."
    ),
)
