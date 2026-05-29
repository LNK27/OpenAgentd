"""In-memory approval queue for Hermes write-intent proposals.

Hermes approval v1 is a per-process, session-scoped review queue. It is an
advisory workflow for Hermes proposals, not a vault-wide security gate:
lead agents may still use ``vault_write`` directly for non-Hermes notes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid7

from app.services.hermes import HermesIntentProposal
from app.services.vault_gatekeeper import (
    VaultDuplicateError,
    VaultIndexUpdateError,
    VaultPathError,
    VaultWriteError,
    VaultWriteIntent,
    get_vault_gatekeeper,
    validate_vault_note_path,
)

HERMES_QUEUE_LIMIT_REASON = "superseded_by_queue_limit"
DEFAULT_MAX_PENDING_PER_SESSION = 50
TERMINAL_STATUSES = {"approved", "rejected", "failed"}


class HermesApprovalError(Exception):
    """Base exception for Hermes approval queue failures."""


class HermesApprovalNotFoundError(HermesApprovalError):
    """Raised when a pending id is missing or belongs to another session."""


class HermesApprovalAlreadyProcessedError(HermesApprovalError):
    """Raised when approving or rejecting a terminal queue entry."""


class HermesApprovalWriteError(HermesApprovalError):
    """Raised when a queue entry could not be written to the vault."""


@dataclass
class PendingHermesIntent:
    """One Hermes intent waiting for lead-agent approval."""

    pending_id: str
    session_id: str
    intent: HermesIntentProposal
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None
    failure_reason: str | None = None
    result_path: str | None = None


@dataclass(frozen=True)
class HermesEnqueueResult:
    """Result of enqueueing Hermes intents."""

    entries: list[PendingHermesIntent]
    evicted_count: int = 0


@dataclass(frozen=True)
class HermesApprovalResult:
    """Result of approving and writing one pending intent."""

    pending_id: str
    path: str
    note_id: str


class HermesApprovalQueue:
    """Process-local queue for Hermes write-intent review."""

    def __init__(
        self,
        *,
        max_pending_per_session: int = DEFAULT_MAX_PENDING_PER_SESSION,
    ) -> None:
        self.max_pending_per_session = max(1, int(max_pending_per_session))
        self._entries: dict[str, PendingHermesIntent] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        session_id: str,
        intents: list[HermesIntentProposal],
    ) -> HermesEnqueueResult:
        """Add valid Hermes intents to the queue for one session."""
        async with self._lock:
            entries = [
                PendingHermesIntent(
                    pending_id=str(uuid7()),
                    session_id=session_id,
                    intent=intent,
                )
                for intent in intents
            ]
            for entry in entries:
                self._entries[entry.pending_id] = entry
            evicted_count = self._evict_oldest_pending_locked(session_id)
            return HermesEnqueueResult(entries=entries, evicted_count=evicted_count)

    async def list_pending(
        self,
        session_id: str,
        *,
        include_non_pending: bool = False,
    ) -> list[PendingHermesIntent]:
        """Return queue entries for one session in creation order."""
        async with self._lock:
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
        approver: str,
    ) -> HermesApprovalResult:
        """Approve a pending intent and write it through the vault gatekeeper."""
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            intent = entry.intent
            rel_path = f"{intent.folder}/{intent.slug}.md"
            try:
                target = validate_vault_note_path(rel_path)
                if target.exists():
                    raise VaultDuplicateError(f"Vault note already exists: {rel_path}")
                result = await get_vault_gatekeeper().write_note(
                    VaultWriteIntent(
                        folder=intent.folder,
                        slug=intent.slug,
                        title=intent.title,
                        note_type=intent.note_type,
                        body=intent.body,
                        status=intent.status,
                        tags=list(intent.tags),
                        source_refs=list(intent.source_refs),
                        relations=list(intent.relations),
                        writer=approver,
                        note_id=intent.note_id,
                        overwrite=False,
                    )
                )
            except VaultDuplicateError as exc:
                self._mark_failed_locked(
                    entry, f"Note already exists at vault/{rel_path}"
                )
                raise HermesApprovalWriteError(
                    entry.failure_reason or str(exc)
                ) from exc
            except VaultIndexUpdateError as exc:
                message = (
                    "Note created but index update failed; note was rolled back. Retry."
                    if exc.rollback_succeeded
                    else (
                        "CRITICAL: Note written but index inconsistent. "
                        f"Manual fix needed at {exc.path}."
                    )
                )
                self._mark_failed_locked(entry, message)
                raise HermesApprovalWriteError(message) from exc
            except VaultPathError as exc:
                self._mark_failed_locked(entry, str(exc))
                raise HermesApprovalWriteError(str(exc)) from exc
            except VaultWriteError as exc:
                message = f"Failed to write vault note at vault/{rel_path}"
                self._mark_failed_locked(entry, message)
                raise HermesApprovalWriteError(message) from exc
            except ValueError as exc:
                self._mark_failed_locked(entry, str(exc))
                raise HermesApprovalWriteError(str(exc)) from exc

            entry.status = "approved"
            entry.result_path = result.path
            entry.updated_at = datetime.now(UTC)
            return HermesApprovalResult(
                pending_id=entry.pending_id,
                path=result.path,
                note_id=result.note_id,
            )

    async def reject(
        self,
        pending_id: str,
        *,
        session_id: str,
        reason: str | None = None,
    ) -> PendingHermesIntent:
        """Reject one pending intent without writing to the vault."""
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            entry.status = "rejected"
            entry.reject_reason = reason.strip() if reason and reason.strip() else None
            entry.updated_at = datetime.now(UTC)
            return entry

    def _evict_oldest_pending_locked(self, session_id: str) -> int:
        pending = [
            entry
            for entry in self._entries.values()
            if entry.session_id == session_id and entry.status == "pending"
        ]
        pending.sort(key=lambda entry: entry.created_at)
        overflow = max(0, len(pending) - self.max_pending_per_session)
        for entry in pending[:overflow]:
            entry.status = "rejected"
            entry.reject_reason = HERMES_QUEUE_LIMIT_REASON
            entry.updated_at = datetime.now(UTC)
        return overflow

    def _get_for_session_locked(
        self,
        pending_id: str,
        session_id: str,
    ) -> PendingHermesIntent:
        entry = self._entries.get(pending_id)
        if entry is None or entry.session_id != session_id:
            raise HermesApprovalNotFoundError(
                f"No Hermes pending intent found for this session: {pending_id}"
            )
        return entry

    def _ensure_pending_locked(self, entry: PendingHermesIntent) -> None:
        if entry.status in TERMINAL_STATUSES:
            raise HermesApprovalAlreadyProcessedError(
                f"Hermes pending intent {entry.pending_id} is already {entry.status}."
            )
        if entry.status != "pending":
            raise HermesApprovalAlreadyProcessedError(
                f"Hermes pending intent {entry.pending_id} is not pending."
            )

    def _mark_failed_locked(self, entry: PendingHermesIntent, reason: str) -> None:
        entry.status = "failed"
        entry.failure_reason = reason
        entry.updated_at = datetime.now(UTC)


_default_queue: HermesApprovalQueue | None = None


def get_hermes_approval_queue() -> HermesApprovalQueue:
    """Return the process-wide Hermes approval queue."""
    global _default_queue
    if _default_queue is None:
        _default_queue = HermesApprovalQueue()
    return _default_queue
