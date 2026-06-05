"""Hermes skill draft review queue and approval write boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import yaml

from app.services import agent_fs, team_manager
from app.services.hermes import HermesSkillDraftProposal

HERMES_SKILL_QUEUE_LIMIT_REASON = "superseded_by_queue_limit"
DEFAULT_MAX_SKILL_DRAFT_ENTRIES_PER_SESSION = 50
TERMINAL_STATUSES = {"approved", "rejected", "failed"}


class HermesSkillDraftError(Exception):
    """Base error for Hermes skill draft approval flow."""


class HermesSkillDraftNotFoundError(HermesSkillDraftError):
    """Raised when a pending id is missing or not visible in this session."""


class HermesSkillDraftAlreadyProcessedError(HermesSkillDraftError):
    """Raised when an entry is not pending."""


class HermesSkillDraftWriteError(HermesSkillDraftError):
    """Raised when approval cannot create the skill file."""


@dataclass
class PendingHermesSkillDraft:
    """One Hermes skill draft waiting for lead-agent approval."""

    pending_id: str
    session_id: str
    draft: HermesSkillDraftProposal
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class HermesSkillDraftEnqueueResult:
    """Result of enqueueing Hermes skill drafts."""

    entries: list[PendingHermesSkillDraft]
    evicted_count: int = 0
    pruned_count: int = 0


@dataclass(frozen=True)
class HermesSkillDraftApprovalResult:
    """Result of approving and creating one skill file."""

    pending_id: str
    name: str
    path: str


def render_skill_markdown(draft: HermesSkillDraftProposal) -> str:
    """Render a validated Hermes draft as OpenAgentd-owned SKILL.md content."""
    metadata = {
        "name": agent_fs.validate_skill_name(draft.name),
        "description": draft.description.strip(),
    }
    if not metadata["description"]:
        raise HermesSkillDraftWriteError("Skill description cannot be empty.")
    body = draft.body.strip()
    if not body:
        raise HermesSkillDraftWriteError("Skill body cannot be empty.")
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{frontmatter}\n---\n{body}\n"


class HermesSkillDraftQueue:
    """In-memory per-process queue for Hermes skill drafts."""

    def __init__(
        self,
        *,
        max_entries_per_session: int = DEFAULT_MAX_SKILL_DRAFT_ENTRIES_PER_SESSION,
    ) -> None:
        self.max_entries_per_session = max(1, int(max_entries_per_session))
        self._entries: dict[str, PendingHermesSkillDraft] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        session_id: str,
        drafts: list[HermesSkillDraftProposal],
    ) -> HermesSkillDraftEnqueueResult:
        """Enqueue valid skill drafts for one session."""
        async with self._lock:
            entries = [
                PendingHermesSkillDraft(
                    pending_id=str(uuid4()),
                    session_id=session_id,
                    draft=draft,
                )
                for draft in drafts
            ]
            for entry in entries:
                self._entries[entry.pending_id] = entry
            pruned_count, evicted_count = self._enforce_limit_locked(session_id)
            return HermesSkillDraftEnqueueResult(
                entries=[
                    entry
                    for entry in entries
                    if entry.pending_id in self._entries and entry.status == "pending"
                ],
                evicted_count=evicted_count,
                pruned_count=pruned_count,
            )

    async def list_pending(
        self,
        session_id: str,
        *,
        include_non_pending: bool = False,
    ) -> list[PendingHermesSkillDraft]:
        """List entries visible to one session."""
        async with self._lock:
            self._enforce_limit_locked(session_id)
            entries = [
                entry
                for entry in self._entries.values()
                if entry.session_id == session_id
                and (include_non_pending or entry.status == "pending")
            ]
            return sorted(entries, key=lambda entry: entry.created_at)

    async def approve(
        self,
        pending_id: str,
        *,
        session_id: str,
    ) -> HermesSkillDraftApprovalResult:
        """Approve a pending draft and create its SKILL.md file."""
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            try:
                content = render_skill_markdown(entry.draft)
                record = agent_fs.write_skill(entry.draft.name, content, create=True)
                team_manager.invalidate_skill_cache()
            except (
                HermesSkillDraftWriteError,
                agent_fs.AgentFsPathError,
                agent_fs.AgentFsConflictError,
                OSError,
            ) as exc:
                entry.status = "failed"
                entry.failure_reason = str(exc)
                entry.updated_at = datetime.now(UTC)
                raise HermesSkillDraftWriteError(str(exc)) from exc
            entry.status = "approved"
            entry.updated_at = datetime.now(UTC)
            return HermesSkillDraftApprovalResult(
                pending_id=entry.pending_id,
                name=entry.draft.name,
                path=record.path,
            )

    async def reject(
        self,
        pending_id: str,
        *,
        session_id: str,
        reason: str | None = None,
    ) -> PendingHermesSkillDraft:
        """Reject one pending draft without writing files."""
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            entry.status = "rejected"
            entry.reject_reason = (
                reason.strip() if isinstance(reason, str) and reason.strip() else None
            )
            entry.updated_at = datetime.now(UTC)
            self._enforce_limit_locked(session_id)
            return entry

    def _enforce_limit_locked(self, session_id: str) -> tuple[int, int]:
        entries = sorted(
            [
                entry
                for entry in self._entries.values()
                if entry.session_id == session_id
            ],
            key=lambda entry: entry.created_at,
        )
        overflow = max(0, len(entries) - self.max_entries_per_session)
        pruned_count = 0
        evicted_count = 0
        if overflow <= 0:
            return pruned_count, evicted_count

        terminal = [entry for entry in entries if entry.status in TERMINAL_STATUSES]
        for entry in terminal[:overflow]:
            self._entries.pop(entry.pending_id, None)
            pruned_count += 1
        overflow -= pruned_count
        if overflow <= 0:
            return pruned_count, evicted_count

        pending = [entry for entry in entries if entry.status == "pending"]
        for entry in pending[:overflow]:
            entry.status = "rejected"
            entry.reject_reason = HERMES_SKILL_QUEUE_LIMIT_REASON
            entry.updated_at = datetime.now(UTC)
            self._entries.pop(entry.pending_id, None)
            evicted_count += 1
        return pruned_count, evicted_count

    def _get_for_session_locked(
        self,
        pending_id: str,
        session_id: str,
    ) -> PendingHermesSkillDraft:
        entry = self._entries.get(pending_id)
        if entry is None or entry.session_id != session_id:
            raise HermesSkillDraftNotFoundError(
                f"No Hermes skill draft found for this session: {pending_id}"
            )
        return entry

    def _ensure_pending_locked(self, entry: PendingHermesSkillDraft) -> None:
        if entry.status in TERMINAL_STATUSES:
            raise HermesSkillDraftAlreadyProcessedError(
                f"Hermes skill draft {entry.pending_id} is already {entry.status}."
            )
        if entry.status != "pending":
            raise HermesSkillDraftAlreadyProcessedError(
                f"Hermes skill draft {entry.pending_id} is not pending."
            )


_queue = HermesSkillDraftQueue()


def get_hermes_skill_draft_queue() -> HermesSkillDraftQueue:
    """Return the process-local Hermes skill draft queue singleton."""
    return _queue
