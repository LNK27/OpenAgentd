"""vault_write tool -- structured agent-only writes into the Obsidian vault."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    VaultDuplicateError,
    VaultIndexUpdateError,
    VaultPathError,
    VaultWriteError,
    VaultWriteIntent,
    get_vault_gatekeeper,
)

VALID_VAULT_FOLDERS: tuple[str, ...] = tuple(sorted(VAULT_FOLDERS))


def _writer_from_state(state: Any) -> str:
    if state is None:
        return "agent:unknown"
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return "agent:unknown"
    agent_name = metadata.get("agent_name")
    if not isinstance(agent_name, str) or not agent_name.strip():
        return "agent:unknown"
    return f"agent:{agent_name.strip()}"


async def _vault_write(
    folder: Annotated[
        str,
        Field(
            description=(
                "Vault folder to write into. Must be one of the standard "
                "Obsidian v7 folders."
            )
        ),
    ],
    slug: Annotated[
        str,
        Field(description="Filename stem for the note, without .md suffix."),
    ],
    title: Annotated[str, Field(description="Human-readable note title.")],
    note_type: Annotated[
        str,
        Field(description="Note type stored in frontmatter, e.g. topic, source."),
    ],
    body: Annotated[str, Field(description="Markdown body content for the note.")],
    status: Annotated[
        str,
        Field(description="Frontmatter status value for the note."),
    ] = "draft",
    tags: Annotated[
        list[str],
        Field(description="Frontmatter tags for the note."),
    ] = [],
    source_refs: Annotated[
        list[str],
        Field(description="Frontmatter source references for the note."),
    ] = [],
    relations: Annotated[
        list[str],
        Field(description="Frontmatter wikilinks or relation identifiers."),
    ] = [],
    note_id: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional external reference id stored in frontmatter.",
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Create one durable Obsidian vault note through the gatekeeper.

    Use this for structured, long-lived notes that belong in the user's
    second-brain vault. This tool does not expose raw filesystem writes and
    must not be used to edit index files directly.
    """
    if folder not in VALID_VAULT_FOLDERS:
        allowed = ", ".join(VALID_VAULT_FOLDERS)
        return f"Invalid folder: '{folder}'. Must be one of: {allowed}"

    try:
        result = await get_vault_gatekeeper().write_note(
            VaultWriteIntent(
                folder=folder,
                slug=slug,
                title=title,
                note_type=note_type,
                body=body,
                status=status,
                tags=list(tags),
                source_refs=list(source_refs),
                relations=list(relations),
                writer=_writer_from_state(_state),
                note_id=note_id,
                overwrite=False,
            )
        )
    except VaultDuplicateError:
        return f"Note already exists at vault/{folder}/{slug}.md"
    except VaultIndexUpdateError as exc:
        if exc.rollback_succeeded:
            return "Note created but index update failed; note was rolled back. Retry."
        return (
            "CRITICAL: Note written but index inconsistent. "
            f"Manual fix needed at {exc.path}."
        )
    except VaultPathError as exc:
        message = str(exc)
        if "reserved Windows filename" in message:
            return f"Invalid slug: '{slug}' is reserved on Windows"
        return message
    except VaultWriteError:
        return f"Failed to write vault note at vault/{folder}/{slug}.md"

    return f"Vault note written to {result.path}"


vault_write = Tool(
    _vault_write,
    name="vault_write",
    description=(
        "Create a structured, durable note in the Obsidian vault through the "
        "gatekeeper. Use this for second-brain notes, not raw logs or direct "
        "index editing."
    ),
)
