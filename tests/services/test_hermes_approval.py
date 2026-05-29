"""Tests for the Hermes approval queue service."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import vault_gatekeeper
from app.services.hermes import HermesIntentProposal
from app.services.hermes_approval import (
    HERMES_QUEUE_LIMIT_REASON,
    HermesApprovalAlreadyProcessedError,
    HermesApprovalQueue,
    HermesApprovalWriteError,
)
from app.services.vault_gatekeeper import VAULT_FOLDERS


@pytest.fixture(autouse=True)
def _vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.core.config import settings

    target = tmp_path / "ObsidianVault"
    for folder in VAULT_FOLDERS:
        folder_path = target / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "_index.md").write_text("## Notes\n", encoding="utf-8")
    monkeypatch.setattr(settings, "OPENAGENTD_OBSIDIAN_VAULT_DIR", str(target))
    monkeypatch.setattr(vault_gatekeeper, "_default_gatekeeper", None)
    return target


def _intent(slug: str = "agent-memory") -> HermesIntentProposal:
    return HermesIntentProposal(
        folder="20-topics",
        slug=slug,
        title=f"Title {slug}",
        note_type="topic",
        body=f"Body for {slug}",
        tags=["memory"],
        source_refs=[],
        relations=[],
        note_id=f"hermes-{slug}",
    )


@pytest.mark.asyncio
async def test_enqueue_valid_intents_creates_pending_ids() -> None:
    queue = HermesApprovalQueue()

    result = await queue.enqueue("session-a", [_intent("one"), _intent("two")])

    assert result.evicted_count == 0
    assert [entry.status for entry in result.entries] == ["pending", "pending"]
    assert result.entries[0].pending_id != result.entries[1].pending_id
    assert [entry.intent.slug for entry in await queue.list_pending("session-a")] == [
        "one",
        "two",
    ]


@pytest.mark.asyncio
async def test_list_pending_is_scoped_to_session_id() -> None:
    queue = HermesApprovalQueue()
    await queue.enqueue("session-a", [_intent("a")])
    await queue.enqueue("session-b", [_intent("b")])

    entries = await queue.list_pending("session-a")

    assert [entry.intent.slug for entry in entries] == ["a"]


@pytest.mark.asyncio
async def test_enqueue_rejects_oldest_pending_when_session_limit_exceeded() -> None:
    queue = HermesApprovalQueue(max_pending_per_session=2)
    first = await queue.enqueue("session-a", [_intent("one"), _intent("two")])

    second = await queue.enqueue("session-a", [_intent("three")])

    assert second.evicted_count == 1
    assert first.entries[0].status == "rejected"
    assert first.entries[0].reject_reason == HERMES_QUEUE_LIMIT_REASON
    assert [entry.intent.slug for entry in await queue.list_pending("session-a")] == [
        "two",
        "three",
    ]


@pytest.mark.asyncio
async def test_approve_pending_intent_writes_note_through_gatekeeper(
    _vault_dir: Path,
) -> None:
    queue = HermesApprovalQueue()
    enqueued = await queue.enqueue("session-a", [_intent("approved")])

    result = await queue.approve(
        enqueued.entries[0].pending_id,
        session_id="session-a",
        approver="agent:lead",
    )

    assert result.path == "20-topics/approved.md"
    assert enqueued.entries[0].status == "approved"
    note = (_vault_dir / "20-topics" / "approved.md").read_text(encoding="utf-8")
    assert "writer: agent:lead" in note
    assert "id: hermes-approved" in note


@pytest.mark.asyncio
async def test_approve_revalidates_existing_path_and_does_not_overwrite(
    _vault_dir: Path,
) -> None:
    queue = HermesApprovalQueue()
    enqueued = await queue.enqueue("session-a", [_intent("existing")])
    note_path = _vault_dir / "20-topics" / "existing.md"
    note_path.write_text("original", encoding="utf-8")

    with pytest.raises(HermesApprovalWriteError, match="already exists"):
        await queue.approve(
            enqueued.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        )

    assert note_path.read_text(encoding="utf-8") == "original"
    assert enqueued.entries[0].status == "failed"


@pytest.mark.asyncio
async def test_reject_pending_intent_marks_rejected() -> None:
    queue = HermesApprovalQueue()
    enqueued = await queue.enqueue("session-a", [_intent("reject-me")])

    entry = await queue.reject(
        enqueued.entries[0].pending_id,
        session_id="session-a",
        reason="not useful",
    )

    assert entry.status == "rejected"
    assert entry.reject_reason == "not useful"
    assert await queue.list_pending("session-a") == []


@pytest.mark.asyncio
async def test_double_approve_only_writes_once(_vault_dir: Path) -> None:
    queue = HermesApprovalQueue()
    enqueued = await queue.enqueue("session-a", [_intent("race")])

    results = await asyncio.gather(
        queue.approve(
            enqueued.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        ),
        queue.approve(
            enqueued.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        ),
        return_exceptions=True,
    )

    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], HermesApprovalAlreadyProcessedError)
    assert (_vault_dir / "20-topics" / "race.md").exists()


@pytest.mark.asyncio
async def test_approve_rejected_or_failed_intent_is_terminal(_vault_dir: Path) -> None:
    queue = HermesApprovalQueue()
    rejected = await queue.enqueue("session-a", [_intent("rejected")])
    await queue.reject(
        rejected.entries[0].pending_id,
        session_id="session-a",
        reason="bad",
    )

    with pytest.raises(HermesApprovalAlreadyProcessedError, match="rejected"):
        await queue.approve(
            rejected.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        )

    failed = await queue.enqueue("session-a", [_intent("failed")])
    (_vault_dir / "20-topics" / "failed.md").write_text("exists", encoding="utf-8")
    with pytest.raises(HermesApprovalWriteError):
        await queue.approve(
            failed.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        )
    with pytest.raises(HermesApprovalAlreadyProcessedError, match="failed"):
        await queue.approve(
            failed.entries[0].pending_id,
            session_id="session-a",
            approver="agent:lead",
        )


@pytest.mark.asyncio
async def test_queue_does_not_call_hermes_when_approving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesApprovalQueue()
    enqueued = await queue.enqueue("session-a", [_intent("no-hermes")])

    async def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("Hermes should not be called during approval")

    monkeypatch.setattr("app.services.hermes.propose_write_intents", _boom)

    await queue.approve(
        enqueued.entries[0].pending_id,
        session_id="session-a",
        approver="agent:lead",
    )
