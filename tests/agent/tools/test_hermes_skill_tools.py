from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.agent.tools.builtin import hermes_skill as module
from app.services.hermes import HermesSkillDraftProposal, HermesSkillDraftResult
from app.services.hermes_skill_drafting import HermesSkillDraftQueue


@dataclass
class MockState:
    metadata: dict[str, str]


def _state(session_id: str | None = "session-a") -> MockState:
    metadata = {"agent_name": "lead"}
    if session_id is not None:
        metadata["session_id"] = session_id
    return MockState(metadata=metadata)


async def test_hermes_skill_draft_requires_session_before_calling_hermes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_draft_skills(*args, **kwargs):
        nonlocal called
        called = True
        return HermesSkillDraftResult()

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="draft",
        _injected={"_state": _state(None)},
    )

    assert result == "Hermes skill draft queue requires a session_id."
    assert called is False


async def test_hermes_skill_draft_enqueues_valid_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesSkillDraftQueue()
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    async def fake_draft_skills(*args, **kwargs):
        return HermesSkillDraftResult(
            summary="done",
            valid_drafts=[
                HermesSkillDraftProposal(
                    name="draft-skill",
                    description="Draft helper",
                    body="Body content",
                    rationale="Useful",
                )
            ],
        )

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="draft",
        context="ctx",
        _injected={"_state": _state()},
    )
    payload = json.loads(result)

    assert payload["summary"] == "done"
    assert payload["evicted_count"] == 0
    assert payload["pruned_count"] == 0
    assert payload["valid_drafts"][0]["pending_id"]
    preview = payload["valid_drafts"][0]["preview"]
    assert preview["body_preview"] == "Body content"
    assert preview["body_length"] == len("Body content")


async def test_hermes_skill_draft_observability_attrs_do_not_leak_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesSkillDraftQueue()
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)
    observations: list[dict[str, object]] = []

    def fake_record_second_brain_tool_observation(**kwargs) -> None:
        observations.append(kwargs)

    async def fake_draft_skills(*args, **kwargs):
        return HermesSkillDraftResult(
            valid_drafts=[
                HermesSkillDraftProposal(
                    name="draft-skill",
                    description="private description",
                    body="private body preview",
                    rationale="private rationale",
                )
            ],
        )

    monkeypatch.setattr(
        module,
        "record_second_brain_tool_observation",
        fake_record_second_brain_tool_observation,
    )
    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="private task",
        context="private context",
        _injected={"_state": _state()},
    )
    payload = json.loads(result)

    assert payload["valid_drafts"][0]["pending_id"]
    assert payload["valid_drafts"][0]["preview"]["body_preview"] == (
        "private body preview"
    )
    attributes = observations[-1]["attributes"]
    serialized = str(attributes)
    assert "private task" not in serialized
    assert "private context" not in serialized
    assert "private body preview" not in serialized
    assert "private description" not in serialized
    assert "private rationale" not in serialized
    assert "pending_id" not in serialized
    assert "body_preview" not in serialized


async def test_hermes_skill_draft_schema_error_is_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.hermes import HermesSchemaError

    async def fake_draft_skills(*args, **kwargs):
        raise HermesSchemaError("bad skill draft")

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="draft",
        _injected={"_state": _state()},
    )

    assert result == "Hermes connector schema error: bad skill draft"


async def test_hermes_skill_pending_list_formats_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue(
        "session-a",
        [
            HermesSkillDraftProposal(
                name="draft-skill",
                description="Draft helper",
                body="Body",
            )
        ],
    )
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    result = await module.hermes_skill_pending_list.arun(
        _injected={"_state": _state()},
    )

    assert "Hermes skill drafts:" in result
    assert enqueued.entries[0].pending_id in result
    assert "status: pending" in result
    assert "name: draft-skill" in result
    assert "body_preview: Body" in result


async def test_hermes_skill_pending_approve_writes_skill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue(
        "session-a",
        [
            HermesSkillDraftProposal(
                name="draft-skill",
                description="Draft helper",
                body="Body content",
            )
        ],
    )
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    result = await module.hermes_skill_pending_approve.arun(
        pending_id=enqueued.entries[0].pending_id,
        _injected={"_state": _state()},
    )

    assert "approved" in result
    assert (tmp_path / "draft-skill" / "SKILL.md").is_file()


async def test_hermes_skill_pending_reject_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue(
        "session-a",
        [
            HermesSkillDraftProposal(
                name="draft-skill",
                description="Draft helper",
                body="Body",
            )
        ],
    )
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    result = await module.hermes_skill_pending_reject.arun(
        pending_id=enqueued.entries[0].pending_id,
        reason="not needed",
        _injected={"_state": _state()},
    )

    assert result == "Hermes skill draft rejected: draft-skill"


async def test_hermes_skill_pending_reject_observability_omits_reason_and_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue(
        "session-a",
        [
            HermesSkillDraftProposal(
                name="draft-skill",
                description="Draft helper",
                body="Body",
            )
        ],
    )
    observations: list[dict[str, object]] = []

    def fake_record_second_brain_tool_observation(**kwargs) -> None:
        observations.append(kwargs)

    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)
    monkeypatch.setattr(
        module,
        "record_second_brain_tool_observation",
        fake_record_second_brain_tool_observation,
    )

    await module.hermes_skill_pending_reject.arun(
        pending_id=enqueued.entries[0].pending_id,
        reason="private rejection reason",
        _injected={"_state": _state()},
    )

    attributes = observations[-1]["attributes"]
    serialized = str(attributes)
    assert "private rejection reason" not in serialized
    assert enqueued.entries[0].pending_id not in serialized
