"""vault_update tool -- structured updates for existing Obsidian vault notes."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.builtin._observability import (
    SECOND_BRAIN_ERROR,
    SECOND_BRAIN_OK,
    record_second_brain_tool_observation,
)
from app.agent.tools.registry import InjectedArg, Tool
from app.services.vault_gatekeeper import (
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultPathError,
    VaultUpdateConflictError,
    VaultUpdateIntent,
    VaultWriteError,
    get_vault_gatekeeper,
)


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


async def _vault_update(
    folder: Annotated[str, Field(description="Standard vault folder.")],
    slug: Annotated[str, Field(description="Note filename stem without .md suffix.")],
    expected_sha256: Annotated[
        str,
        Field(
            description="SHA-256 update token from vault_read(include_update_token=True)."
        ),
    ],
    replace_body: Annotated[
        str | None,
        Field(
            description="Replace the Markdown body. Mutually exclusive with append_body."
        ),
    ] = None,
    append_body: Annotated[
        str | None,
        Field(
            description="Append Markdown to the body. Mutually exclusive with replace_body."
        ),
    ] = None,
    status: Annotated[
        str | None, Field(description="Optional frontmatter status.")
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Optional replacement frontmatter tags."),
    ] = None,
    source_refs: Annotated[
        list[str] | None,
        Field(description="Optional replacement source references."),
    ] = None,
    relations: Annotated[
        list[str] | None,
        Field(description="Optional replacement relations."),
    ] = None,
    last_summarized_at: Annotated[
        str | None,
        Field(description="Optional last_summarized_at frontmatter value."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Update one existing Obsidian vault note through the gatekeeper."""
    start = time.perf_counter()
    attrs = _attrs(
        folder,
        slug,
        replace_body,
        append_body,
        status,
        tags,
        source_refs,
        relations,
        last_summarized_at,
    )
    try:
        result = await get_vault_gatekeeper().update_note(
            VaultUpdateIntent(
                folder=folder,
                slug=slug,
                expected_sha256=expected_sha256,
                replace_body=replace_body,
                append_body=append_body,
                status=status,
                tags=tags,
                source_refs=source_refs,
                relations=relations,
                last_summarized_at=last_summarized_at,
                writer=_writer_from_state(_state),
            )
        )
    except VaultUpdateConflictError:
        _record("conflict", SECOND_BRAIN_ERROR, start, attrs)
        return (
            f"Update conflict at vault/{folder}/{slug}.md: note changed since last "
            "read. Read it again and retry with the new update token."
        )
    except VaultNoteNotFoundError:
        _record("not_found", SECOND_BRAIN_ERROR, start, attrs)
        return f"Note not found at vault/{folder}/{slug}.md"
    except VaultMalformedNoteError:
        _record("malformed_frontmatter", SECOND_BRAIN_ERROR, start, attrs)
        return (
            f"Cannot update vault/{folder}/{slug}.md: note frontmatter is missing "
            "or malformed. Run ingest/reconcile first."
        )
    except VaultPathError as exc:
        _record("invalid_path", SECOND_BRAIN_ERROR, start, attrs)
        return str(exc)
    except VaultWriteError:
        _record("write_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Failed to update vault note at vault/{folder}/{slug}.md"
    except ValueError as exc:
        _record("invalid_request", SECOND_BRAIN_ERROR, start, attrs)
        return f"Invalid vault update request: {exc}"

    _record("updated", SECOND_BRAIN_OK, start, {**attrs, "vault.path": result.path})
    return f"Vault note updated at {result.path}"


def _attrs(
    folder: str,
    slug: str,
    replace_body: str | None,
    append_body: str | None,
    status: str | None,
    tags: list[str] | None,
    source_refs: list[str] | None,
    relations: list[str] | None,
    last_summarized_at: str | None,
) -> dict[str, object]:
    metadata_fields_count = sum(
        value is not None
        for value in (status, tags, source_refs, relations, last_summarized_at)
    )
    return {
        "vault.folder": folder,
        "vault.path": f"{folder}/{slug}.md",
        "vault.replace_body_length": len(replace_body or ""),
        "vault.append_body_length": len(append_body or ""),
        "vault.metadata_fields_count": metadata_fields_count,
        "vault.has_replace_body": replace_body is not None,
        "vault.has_append_body": append_body is not None,
    }


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="vault_update",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


vault_update = Tool(
    _vault_update,
    name="vault_update",
    description=(
        "Update an existing Obsidian vault note through the gatekeeper using a "
        "sha256 update token from vault_read. Supports structured body and "
        "allowlisted frontmatter updates only."
    ),
)
