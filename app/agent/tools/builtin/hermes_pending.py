"""Hermes pending approval tools."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool
from app.services.hermes_approval import (
    HermesApprovalAlreadyProcessedError,
    HermesApprovalError,
    HermesApprovalNotFoundError,
    HermesApprovalWriteError,
    PendingHermesIntent,
    get_hermes_approval_queue,
)


async def _hermes_pending_list(
    include_non_pending: Annotated[
        bool,
        Field(description="Include approved, rejected, and failed entries."),
    ] = False,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """List Hermes proposal entries for the current session."""
    session_id = _session_id_from_state(_state)
    if session_id is None:
        return "Hermes approval queue requires a session_id."

    entries = await get_hermes_approval_queue().list_pending(
        session_id,
        include_non_pending=include_non_pending,
    )
    if not entries:
        return "No Hermes pending intents for this session."

    parts = ["Hermes pending intents:"]
    for entry in entries:
        parts.append(_format_entry(entry))
    return "\n\n".join(parts)


async def _hermes_pending_approve(
    pending_id: Annotated[
        str,
        Field(description="Opaque pending id returned by hermes_propose."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Approve one Hermes pending intent and write it to the vault."""
    session_id = _session_id_from_state(_state)
    if session_id is None:
        return "Hermes approval queue requires a session_id."

    try:
        result = await get_hermes_approval_queue().approve(
            pending_id,
            session_id=session_id,
            approver=_writer_from_state(_state),
        )
    except HermesApprovalNotFoundError as exc:
        return f"Hermes pending intent not found: {exc}"
    except HermesApprovalAlreadyProcessedError as exc:
        return f"Hermes pending intent already processed: {exc}"
    except HermesApprovalWriteError as exc:
        return f"Hermes approval failed: {exc}"
    except HermesApprovalError as exc:
        return f"Hermes approval error: {exc}"

    return f"Hermes pending intent approved and written to {result.path}"


async def _hermes_pending_reject(
    pending_id: Annotated[
        str,
        Field(description="Opaque pending id returned by hermes_propose."),
    ],
    reason: Annotated[
        str | None,
        Field(description="Optional reason for rejecting this proposal."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Reject one Hermes pending intent without writing to the vault."""
    session_id = _session_id_from_state(_state)
    if session_id is None:
        return "Hermes approval queue requires a session_id."

    try:
        entry = await get_hermes_approval_queue().reject(
            pending_id,
            session_id=session_id,
            reason=reason,
        )
    except HermesApprovalNotFoundError as exc:
        return f"Hermes pending intent not found: {exc}"
    except HermesApprovalAlreadyProcessedError as exc:
        return f"Hermes pending intent already processed: {exc}"
    except HermesApprovalError as exc:
        return f"Hermes approval error: {exc}"

    return f"Hermes pending intent rejected: {entry.intent.slug}"


def _format_entry(entry: PendingHermesIntent) -> str:
    intent = entry.intent
    lines = [
        f"pending_id: {entry.pending_id}",
        f"status: {entry.status}",
        f"path: {intent.folder}/{intent.slug}.md",
        f"title: {intent.title}",
        f"type: {intent.note_type}",
    ]
    if intent.tags:
        lines.append(f"tags: {', '.join(intent.tags)}")
    if entry.reject_reason:
        lines.append(f"reject_reason: {entry.reject_reason}")
    if entry.failure_reason:
        lines.append(f"failure_reason: {entry.failure_reason}")
    return "\n".join(lines)


def _session_id_from_state(state: Any) -> str | None:
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    session_id = metadata.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    return session_id.strip()


def _writer_from_state(state: Any) -> str:
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return "agent:unknown"
    agent_name = metadata.get("agent_name")
    if not isinstance(agent_name, str) or not agent_name.strip():
        return "agent:unknown"
    return f"agent:{agent_name.strip()}"


hermes_pending_list = Tool(
    _hermes_pending_list,
    name="hermes_pending_list",
    description="List Hermes approval queue entries for the current session.",
)

hermes_pending_approve = Tool(
    _hermes_pending_approve,
    name="hermes_pending_approve",
    description=(
        "Approve one pending Hermes proposal and write it to the Obsidian vault "
        "through the gatekeeper. This does not call Hermes."
    ),
)

hermes_pending_reject = Tool(
    _hermes_pending_reject,
    name="hermes_pending_reject",
    description="Reject one pending Hermes proposal without writing to the vault.",
)
