from __future__ import annotations

import asyncio
import re

import pytest

from app.services.hermes import HermesSkillDraftProposal
from app.services.hermes_skill_drafting import (
    HermesSkillDraftAlreadyProcessedError,
    HermesSkillDraftNotFoundError,
    HermesSkillDraftQueue,
)


def _draft(name: str = "draft-skill") -> HermesSkillDraftProposal:
    return HermesSkillDraftProposal(
        name=name,
        description=f"Description for {name}",
        body=f"Body for {name}",
    )


async def test_enqueue_creates_uuid4_pending_ids() -> None:
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    assert len(result.entries) == 1
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        result.entries[0].pending_id,
    )


async def test_list_is_scoped_by_session() -> None:
    queue = HermesSkillDraftQueue()
    await queue.enqueue("session-a", [_draft("a")])
    await queue.enqueue("session-b", [_draft("b")])

    assert [entry.draft.name for entry in await queue.list_pending("session-a")] == [
        "a"
    ]
    assert [entry.draft.name for entry in await queue.list_pending("session-b")] == [
        "b"
    ]


async def test_queue_limit_prunes_terminal_before_evicting_pending() -> None:
    queue = HermesSkillDraftQueue(max_entries_per_session=3)
    first = await queue.enqueue("session-a", [_draft("one"), _draft("two")])
    await queue.reject(first.entries[0].pending_id, session_id="session-a")

    result = await queue.enqueue("session-a", [_draft("three"), _draft("four")])

    assert result.pruned_count == 1
    assert result.evicted_count == 0
    entries = await queue.list_pending("session-a", include_non_pending=True)
    assert [entry.draft.name for entry in entries] == ["two", "three", "four"]


async def test_queue_limit_evicts_oldest_pending_when_needed() -> None:
    queue = HermesSkillDraftQueue(max_entries_per_session=2)
    first = await queue.enqueue("session-a", [_draft("one"), _draft("two")])

    result = await queue.enqueue("session-a", [_draft("three")])

    assert result.pruned_count == 0
    assert result.evicted_count == 1
    with pytest.raises(HermesSkillDraftNotFoundError):
        await queue.approve(first.entries[0].pending_id, session_id="session-a")
    remaining = await queue.list_pending("session-a")
    assert [entry.draft.name for entry in remaining] == ["two", "three"]


async def test_reject_marks_entry_terminal() -> None:
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    entry = await queue.reject(
        result.entries[0].pending_id,
        session_id="session-a",
        reason="no",
    )

    assert entry.status == "rejected"
    assert entry.reject_reason == "no"
    with pytest.raises(HermesSkillDraftAlreadyProcessedError):
        await queue.approve(result.entries[0].pending_id, session_id="session-a")


async def test_double_approve_only_one_wins(monkeypatch, tmp_path) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])
    pending_id = result.entries[0].pending_id

    outcomes = await asyncio.gather(
        queue.approve(pending_id, session_id="session-a"),
        queue.approve(pending_id, session_id="session-a"),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert (
        sum(
            isinstance(item, HermesSkillDraftAlreadyProcessedError) for item in outcomes
        )
        == 1
    )
    assert (tmp_path / "draft-skill" / "SKILL.md").is_file()


async def test_approve_writes_skill_and_invalidates_cache(
    monkeypatch, tmp_path
) -> None:
    from app.services import agent_fs
    from app.services import hermes_skill_drafting as module

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    invalidated = False

    def fake_invalidate() -> None:
        nonlocal invalidated
        invalidated = True

    monkeypatch.setattr(module.team_manager, "invalidate_skill_cache", fake_invalidate)
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    approved = await queue.approve(result.entries[0].pending_id, session_id="session-a")

    assert approved.name == "draft-skill"
    assert invalidated is True
    content = (tmp_path / "draft-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert content.startswith(
        "---\nname: draft-skill\ndescription: Description for draft-skill\n---\n"
    )
    assert "Body for draft-skill\n" in content
