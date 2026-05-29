"""Tests for the hermes_propose built-in tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.builtin.hermes_propose import hermes_propose
from app.services.hermes import (
    HermesIntentProposal,
    HermesProposal,
    HermesProposalRequest,
    HermesUnavailableError,
)


def test_hermes_propose_schema_hides_write_control_fields() -> None:
    properties = hermes_propose.definition["function"]["parameters"]["properties"]

    assert "writer" not in properties
    assert "overwrite" not in properties
    assert "last_summarized_at" not in properties
    assert "status" not in properties


@pytest.mark.asyncio
async def test_hermes_propose_formats_structured_output() -> None:
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
        )

    call = mock_propose.await_args
    assert call is not None
    request = call.args[0]
    assert isinstance(request, HermesProposalRequest)
    assert request.task == "Draft memory"
    assert "valid_intents" in result
    assert '"folder": "20-topics"' in result
    assert '"slug": "agent-memory"' in result
    assert '"status": "draft"' in result
    assert "conflicts" in result
    assert "vault_write will reject" in result


@pytest.mark.asyncio
async def test_hermes_propose_maps_unavailable_error() -> None:
    with patch(
        "app.agent.tools.builtin.hermes_propose.propose_write_intents",
        new=AsyncMock(side_effect=HermesUnavailableError("Hermes is disabled.")),
    ):
        result = await hermes_propose.arun(task="Draft memory")

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
        await hermes_propose.arun(task="Draft memory")

    mock_write.assert_not_called()
