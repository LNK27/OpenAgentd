"""hermes_propose tool -- request proposal-only write intents from Hermes."""

from __future__ import annotations

import json
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
from app.services.hermes_approval import get_hermes_approval_queue
from app.services.hermes import (
    HermesConnectionError,
    HermesIntentProposal,
    HermesProposal,
    HermesProposalRequest,
    HermesSchemaError,
    HermesTimeoutError,
    HermesUnavailableError,
    propose_write_intents,
)


async def _hermes_propose(
    task: Annotated[
        str,
        Field(description="The memory or drafting task Hermes should analyze."),
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
    target_folder: Annotated[
        str | None,
        Field(description="Optional target vault folder hint for new-note proposals."),
    ] = None,
    max_intents: Annotated[
        int,
        Field(description="Maximum write intents to request, clamped to 1..20."),
    ] = 5,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Ask Hermes for structured vault write-intent proposals without writing.

    Use this to draft candidate second-brain notes. The returned intents are
    proposals only; to persist a Hermes proposal, review the returned pending
    id and call hermes_pending_approve. Calling this tool again creates new
    pending entries; reject old entries if they are no longer useful.
    """
    start = time.perf_counter()
    attrs = _attrs(
        context=context,
        max_intents=max_intents,
        target_folder=target_folder,
    )
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record("missing_session", SECOND_BRAIN_ERROR, start, attrs)
        return "Hermes approval queue requires a session_id."

    try:
        proposal = await propose_write_intents(
            HermesProposalRequest(
                task=task,
                context=context,
                target_folder=target_folder,
                max_intents=max_intents,
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

    enqueued = await get_hermes_approval_queue().enqueue(
        session_id,
        proposal.valid_intents,
    )
    _record(
        "enqueued",
        SECOND_BRAIN_OK,
        start,
        {
            **attrs,
            "hermes.valid_count": len(proposal.valid_intents),
            "hermes.conflict_count": len(proposal.conflicts),
            "hermes.invalid_count": len(proposal.invalid_intents),
            "hermes.pending_count": len(enqueued.entries),
            "hermes.evicted_count": enqueued.evicted_count,
        },
    )
    return _format_proposal(
        proposal,
        pending_ids=[entry.pending_id for entry in enqueued.entries],
        evicted_count=enqueued.evicted_count,
    )


def _attrs(
    *,
    context: str,
    max_intents: int,
    target_folder: str | None,
) -> dict[str, object]:
    attrs: dict[str, object] = {
        "hermes.context_length": len(context or ""),
        "hermes.max_intents": max_intents,
    }
    if target_folder:
        attrs["vault.folder"] = target_folder
    return attrs


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="hermes_propose",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


def _format_proposal(
    proposal: HermesProposal,
    *,
    pending_ids: list[str] | None = None,
    evicted_count: int = 0,
) -> str:
    pending_ids = pending_ids or []
    payload = {
        "summary": proposal.summary,
        "warnings": proposal.warnings,
        "model_info": proposal.model_info,
        "evicted_count": evicted_count,
        "valid_intents": [
            {
                "pending_id": pending_id,
                "preview": _intent_preview(intent),
                "body_truncated": intent.body_truncated,
                "warnings": intent.warnings,
            }
            for pending_id, intent in zip(pending_ids, proposal.valid_intents)
        ],
        "conflicts": [
            {
                "preview": _intent_preview(intent),
                "warning": intent.warning,
                "body_truncated": intent.body_truncated,
                "warnings": intent.warnings,
            }
            for intent in proposal.conflicts
        ],
        "invalid_intents": [
            {
                "folder": intent.folder,
                "slug": intent.slug,
                "title": intent.title,
                "invalid_reason": intent.invalid_reason,
            }
            for intent in proposal.invalid_intents
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _intent_preview(intent: HermesIntentProposal) -> dict[str, Any]:
    payload = intent.as_vault_write_params()
    payload["path"] = f"{intent.folder}/{intent.slug}.md"
    return payload


def _session_id_from_state(state: Any) -> str | None:
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    session_id = metadata.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    return session_id.strip()


hermes_propose = Tool(
    _hermes_propose,
    name="hermes_propose",
    description=(
        "Ask the Hermes sidecar for structured vault write-intent proposals. "
        "This tool never writes to the Obsidian vault; it creates pending "
        "Hermes approval entries that can be reviewed with hermes_pending_list "
        "and persisted with hermes_pending_approve."
    ),
)
