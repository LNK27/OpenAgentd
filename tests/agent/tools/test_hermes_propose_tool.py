"""Tests for the hermes_propose built-in tool."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.builtin.hermes_propose import hermes_propose
from app.services import hermes_approval
from app.services.hermes import (
    HermesIntentProposal,
    HermesProposal,
    HermesProposalRequest,
    HermesUnavailableError,
)


@dataclass
class MockState:
    metadata: dict[str, str]


@pytest.fixture(autouse=True)
def _reset_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes_approval, "_default_queue", None)


def test_hermes_propose_schema_hides_write_control_fields() -> None:
    properties = hermes_propose.definition["function"]["parameters"]["properties"]

    assert "writer" not in properties
    assert "overwrite" not in properties
    assert "last_summarized_at" not in properties
    assert "status" not in properties


@pytest.mark.asyncio
async def test_hermes_propose_enqueues_valid_intents_and_formats_output() -> None:
    proposal = HermesProposal(
        summary="Created proposals.",
        valid_intents=[
            HermesIntentProposal(
                folder="20-topics",
                slug="agent-memory",
                title="Agent Memory",
                note_type="topic",
                body="Body",
                tags=["memory"],
                source_refs=[],
                relations=[],
                note_id="h1",
                status="draft",
            )
        ],
        conflicts=[
            HermesIntentProposal(
                folder="20-topics",
                slug="existing",
                title="Existing",
                note_type="topic",
                body="Body",
                tags=[],
                source_refs=[],
                relations=[],
                status="draft",
                exists_conflict=True,
                warning=(
                    "note already exists at vault/20-topics/existing.md; "
                    "vault_write will reject without overwrite"
                ),
            )
        ],
        invalid_intents=[],
        warnings=["status 'published' was overridden to 'draft'"],
        model_info={"model": "hermes-local"},
    )

    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=AsyncMock(return_value=proposal),
    ) as mock_propose:
        result = await hermes_propose.arun(
            task="Draft memory",
            context="Context",
            target_folder="20-topics",
            max_intents=2,
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )

    call = mock_propose.await_args
    assert call is not None
    request = call.args[0]
    assert isinstance(request, HermesProposalRequest)
    assert request.task == "Draft memory"
    assert '"pending_id":' in result
    assert "valid_intents" in result
    assert '"folder": "20-topics"' in result
    assert '"slug": "agent-memory"' in result
    assert '"status": "draft"' in result
    assert "vault_write_params" not in result
    assert '"evicted_count": 0' in result
    assert "conflicts" in result
    assert "vault_write will reject" in result

    pending = await hermes_approval.get_hermes_approval_queue().list_pending(
        "session-a"
    )
    assert [entry.intent.slug for entry in pending] == ["agent-memory"]


@pytest.mark.asyncio
async def test_hermes_propose_maps_unavailable_error() -> None:
    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=AsyncMock(side_effect=HermesUnavailableError("Hermes is disabled.")),
    ):
        result = await hermes_propose.arun(
            task="Draft memory",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )

    assert result == "Hermes connector unavailable: Hermes is disabled."


@pytest.mark.asyncio
async def test_hermes_propose_does_not_call_vault_write() -> None:
    with (
        patch(
            "app.agent.tools.builtin.hermes_propose.propose_write_intents",
            new=AsyncMock(return_value=HermesProposal(summary="No writes.")),
        ),
        patch("app.agent.tools.builtin.vault_write.vault_write.arun") as mock_write,
    ):
        await hermes_propose.arun(
            task="Draft memory",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )

    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_hermes_propose_requires_session_id_before_calling_hermes() -> None:
    mock_propose = AsyncMock(return_value=HermesProposal(summary="No writes."))

    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=mock_propose,
    ):
        result = await hermes_propose.arun(task="Draft memory")

    assert result == "Hermes approval queue requires a session_id."
    mock_propose.assert_not_called()


@pytest.mark.asyncio
async def test_hermes_propose_repeated_calls_create_multiple_pending_entries() -> None:
    proposal = HermesProposal(
        valid_intents=[
            HermesIntentProposal(
                folder="20-topics",
                slug="repeat",
                title="Repeat",
                note_type="topic",
                body="Body",
            )
        ]
    )

    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=AsyncMock(return_value=proposal),
    ):
        await hermes_propose.arun(
            task="Draft memory",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )
        await hermes_propose.arun(
            task="Draft memory",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )

    pending = await hermes_approval.get_hermes_approval_queue().list_pending(
        "session-a"
    )
    assert [entry.intent.slug for entry in pending] == ["repeat", "repeat"]


@pytest.mark.asyncio
async def test_hermes_propose_reports_evicted_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = hermes_approval.HermesApprovalQueue(max_pending_per_session=1)
    monkeypatch.setattr(hermes_approval, "_default_queue", queue)
    first = HermesProposal(
        valid_intents=[
            HermesIntentProposal(
                folder="20-topics",
                slug="first",
                title="First",
                note_type="topic",
                body="Body",
            )
        ]
    )
    second = HermesProposal(
        valid_intents=[
            HermesIntentProposal(
                folder="20-topics",
                slug="second",
                title="Second",
                note_type="topic",
                body="Body",
            )
        ]
    )

    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=AsyncMock(side_effect=[first, second]),
    ):
        await hermes_propose.arun(
            task="Draft first",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )
        result = await hermes_propose.arun(
            task="Draft second",
            _injected={"_state": MockState(metadata={"session_id": "session-a"})},
        )

    assert '"evicted_count": 1' in result
