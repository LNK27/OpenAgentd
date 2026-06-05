"""Hermes skill draft and pending approval tools."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.builtin._observability import (
    SECOND_BRAIN_ERROR,
    SECOND_BRAIN_OK,
    record_second_brain_tool_observation,
)
from app.agent.tools.registry import InjectedArg, Tool
from app.services import agent_fs
from app.services.hermes import (
    HermesConnectionError,
    HermesSchemaError,
    HermesSkillDraftProposal,
    HermesSkillDraftRequest,
    HermesTimeoutError,
    HermesUnavailableError,
    draft_skills,
)
from app.services.hermes_skill_drafting import (
    HermesSkillDraftAlreadyProcessedError,
    HermesSkillDraftError,
    HermesSkillDraftNotFoundError,
    HermesSkillDraftWriteError,
    PendingHermesSkillDraft,
    get_hermes_skill_draft_queue,
)

_BODY_PREVIEW_CHARS = 4000


async def _hermes_skill_draft(
    task: Annotated[
        str,
        Field(description="The skill drafting task Hermes should analyze."),
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
    max_drafts: Annotated[
        int,
        Field(description="Maximum skill drafts to request, clamped by Hermes."),
    ] = 3,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Ask Hermes for structured skill drafts without writing files."""
    start = time.perf_counter()
    attrs = {
        "skill.task_length": len(task or ""),
        "skill.context_length": len(context or ""),
        "skill.max_drafts": max_drafts,
    }
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record(
            "hermes_skill_draft", "missing_session", SECOND_BRAIN_ERROR, start, attrs
        )
        return "Hermes skill draft queue requires a session_id."

    try:
        result = await draft_skills(
            HermesSkillDraftRequest(
                task=task,
                context=context,
                max_drafts=max_drafts,
            )
        )
    except HermesUnavailableError as exc:
        _record("hermes_skill_draft", "unavailable", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector unavailable: {exc}"
    except HermesTimeoutError as exc:
        _record("hermes_skill_draft", "timeout", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector timed out: {exc}"
    except HermesConnectionError as exc:
        _record(
            "hermes_skill_draft",
            "connection_error",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes connector connection failed: {exc}"
    except HermesSchemaError as exc:
        _record("hermes_skill_draft", "schema_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector schema error: {exc}"

    enqueued = await get_hermes_skill_draft_queue().enqueue(
        session_id,
        result.valid_drafts,
    )
    _record(
        "hermes_skill_draft",
        "enqueued",
        SECOND_BRAIN_OK,
        start,
        {
            **attrs,
            "skill.draft_count": len(result.valid_drafts),
            "skill.conflict_count": len(result.conflicts),
            "skill.invalid_count": len(result.invalid_drafts),
            "skill.pending_count": len(enqueued.entries),
            "skill.evicted_count": enqueued.evicted_count,
            "skill.pruned_count": enqueued.pruned_count,
        },
    )
    return json.dumps(
        {
            "summary": result.summary,
            "warnings": result.warnings,
            "model_info": result.model_info,
            "evicted_count": enqueued.evicted_count,
            "pruned_count": enqueued.pruned_count,
            "valid_drafts": [
                {
                    "pending_id": entry.pending_id,
                    "preview": _preview(entry.draft),
                }
                for entry in enqueued.entries
            ],
            "conflicts": [
                {
                    "preview": _preview(draft),
                    "warning": draft.warning,
                }
                for draft in result.conflicts
            ],
            "invalid_drafts": [
                {
                    "name": draft.name,
                    "invalid_reason": draft.invalid_reason,
                }
                for draft in result.invalid_drafts
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


async def _hermes_skill_pending_list(
    include_non_pending: Annotated[
        bool,
        Field(description="Include approved, rejected, and failed skill drafts."),
    ] = False,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """List Hermes skill draft entries for the current session."""
    start = time.perf_counter()
    attrs = {"skill.include_non_pending": include_non_pending}
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record(
            "hermes_skill_pending_list",
            "missing_session",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return "Hermes skill draft queue requires a session_id."

    entries = await get_hermes_skill_draft_queue().list_pending(
        session_id,
        include_non_pending=include_non_pending,
    )
    if not entries:
        _record(
            "hermes_skill_pending_list",
            "empty",
            SECOND_BRAIN_OK,
            start,
            {**attrs, "skill.pending_count": 0},
        )
        return "No Hermes skill drafts for this session."

    _record(
        "hermes_skill_pending_list",
        "listed",
        SECOND_BRAIN_OK,
        start,
        {**attrs, "skill.pending_count": len(entries)},
    )
    parts = ["Hermes skill drafts:"]
    for entry in entries:
        parts.append(_format_entry(entry))
    return "\n\n".join(parts)


async def _hermes_skill_pending_approve(
    pending_id: Annotated[
        str,
        Field(description="Opaque pending id returned by hermes_skill_draft."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Approve one Hermes skill draft and create its SKILL.md file."""
    start = time.perf_counter()
    attrs: dict[str, object] = {}
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record(
            "hermes_skill_pending_approve",
            "missing_session",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return "Hermes skill draft queue requires a session_id."

    try:
        result = await get_hermes_skill_draft_queue().approve(
            pending_id,
            session_id=session_id,
        )
    except HermesSkillDraftNotFoundError as exc:
        _record(
            "hermes_skill_pending_approve",
            "not_found",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft not found: {exc}"
    except HermesSkillDraftAlreadyProcessedError as exc:
        _record(
            "hermes_skill_pending_approve",
            "already_processed",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft already processed: {exc}"
    except HermesSkillDraftWriteError as exc:
        _record(
            "hermes_skill_pending_approve",
            "write_error",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft approval failed: {exc}"
    except HermesSkillDraftError as exc:
        _record(
            "hermes_skill_pending_approve",
            "approval_error",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft approval error: {exc}"

    relative_path = _relative_skill_path(result.path)
    _record(
        "hermes_skill_pending_approve",
        "approved",
        SECOND_BRAIN_OK,
        start,
        {
            "skill.name": result.name,
            "skill.path_length": len(relative_path),
        },
    )
    return f"Hermes skill draft approved and written to {relative_path}"


async def _hermes_skill_pending_reject(
    pending_id: Annotated[
        str,
        Field(description="Opaque pending id returned by hermes_skill_draft."),
    ],
    reason: Annotated[
        str | None,
        Field(description="Optional reason for rejecting this skill draft."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Reject one Hermes skill draft without writing files."""
    start = time.perf_counter()
    attrs: dict[str, object] = {}
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record(
            "hermes_skill_pending_reject",
            "missing_session",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return "Hermes skill draft queue requires a session_id."

    try:
        entry = await get_hermes_skill_draft_queue().reject(
            pending_id,
            session_id=session_id,
            reason=reason,
        )
    except HermesSkillDraftNotFoundError as exc:
        _record(
            "hermes_skill_pending_reject",
            "not_found",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft not found: {exc}"
    except HermesSkillDraftAlreadyProcessedError as exc:
        _record(
            "hermes_skill_pending_reject",
            "already_processed",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft already processed: {exc}"
    except HermesSkillDraftError as exc:
        _record(
            "hermes_skill_pending_reject",
            "approval_error",
            SECOND_BRAIN_ERROR,
            start,
            attrs,
        )
        return f"Hermes skill draft approval error: {exc}"

    _record(
        "hermes_skill_pending_reject",
        "rejected",
        SECOND_BRAIN_OK,
        start,
        {"skill.name": entry.draft.name},
    )
    return f"Hermes skill draft rejected: {entry.draft.name}"


def _preview(draft: HermesSkillDraftProposal) -> dict[str, Any]:
    body_preview = draft.body[:_BODY_PREVIEW_CHARS]
    return {
        "name": draft.name,
        "description": draft.description,
        "body_preview": body_preview,
        "body_length": len(draft.body),
        "body_truncated": draft.body_truncated,
        "body_preview_truncated": len(draft.body) > len(body_preview),
        "rationale": draft.rationale,
        "warnings": draft.warnings,
    }


def _format_entry(entry: PendingHermesSkillDraft) -> str:
    preview = _preview(entry.draft)
    lines = [
        f"pending_id: {entry.pending_id}",
        f"status: {entry.status}",
        f"name: {preview['name']}",
        f"description: {preview['description']}",
        f"body_length: {preview['body_length']}",
        f"body_preview_truncated: {preview['body_preview_truncated']}",
        f"body_preview: {preview['body_preview']}",
    ]
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


def _relative_skill_path(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(agent_fs.skills_dir()).as_posix()
    except ValueError:
        return Path(path).name


def _record(
    tool: str,
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool=tool,
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


hermes_skill_draft = Tool(
    _hermes_skill_draft,
    name="hermes_skill_draft",
    description=(
        "Ask Hermes for structured skill drafts. This never writes skill files; "
        "it creates pending skill draft entries for lead review."
    ),
)

hermes_skill_pending_list = Tool(
    _hermes_skill_pending_list,
    name="hermes_skill_pending_list",
    description="List Hermes skill draft queue entries for the current session.",
)

hermes_skill_pending_approve = Tool(
    _hermes_skill_pending_approve,
    name="hermes_skill_pending_approve",
    description=(
        "Approve one pending Hermes skill draft and create a new SKILL.md "
        "through OpenAgentd. This does not call Hermes."
    ),
)

hermes_skill_pending_reject = Tool(
    _hermes_skill_pending_reject,
    name="hermes_skill_pending_reject",
    description="Reject one pending Hermes skill draft without writing files.",
)
