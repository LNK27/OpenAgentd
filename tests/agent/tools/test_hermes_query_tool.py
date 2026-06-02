"""Tests for the hermes_query built-in tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.builtin.hermes_query import hermes_query
from app.services.hermes import (
    HermesConnectionError,
    HermesQueryItem,
    HermesQueryRequest,
    HermesQueryResult,
    HermesSchemaError,
    HermesTimeoutError,
    HermesUnavailableError,
)


def test_hermes_query_schema_hides_write_control_fields() -> None:
    properties = hermes_query.definition["function"]["parameters"]["properties"]

    assert "writer" not in properties
    assert "overwrite" not in properties
    assert "vault_write_params" not in properties
    assert "pending_id" not in properties


@pytest.mark.asyncio
async def test_hermes_query_formats_structured_output() -> None:
    result_payload = HermesQueryResult(
        answer="Use vault_write for direct non-Hermes notes.",
        items=[
            HermesQueryItem(
                path="20-topics/vault-write.md",
                title="Vault Write",
                excerpt="Lead agents can write through the gatekeeper.",
                score=0.82,
                tags=["vault"],
            )
        ],
        warnings=["partial recall"],
        model_info={"model": "hermes-local"},
    )

    with patch(
        "app.agent.tools.builtin.hermes_query.query_recall",
        new=AsyncMock(return_value=result_payload),
    ) as mock_query:
        result = await hermes_query.arun(
            query="How do agents write notes?",
            context="Context",
            max_results=3,
        )

    call = mock_query.await_args
    assert call is not None
    request = call.args[0]
    assert isinstance(request, HermesQueryRequest)
    assert request.query == "How do agents write notes?"
    assert request.context == "Context"
    assert request.max_results == 3
    assert '"answer": "Use vault_write for direct non-Hermes notes."' in result
    assert '"path": "20-topics/vault-write.md"' in result
    assert '"score": 0.82' in result
    assert "vault_write_params" not in result
    assert "pending_id" not in result


@pytest.mark.asyncio
async def test_hermes_query_maps_errors() -> None:
    cases = [
        (HermesUnavailableError("disabled"), "Hermes connector unavailable: disabled"),
        (HermesTimeoutError("slow"), "Hermes connector timed out: slow"),
        (
            HermesConnectionError("refused"),
            "Hermes connector connection failed: refused",
        ),
        (HermesSchemaError("bad"), "Hermes connector schema error: bad"),
    ]

    for error, expected in cases:
        with patch(
            "app.agent.tools.builtin.hermes_query.query_recall",
            new=AsyncMock(side_effect=error),
        ):
            result = await hermes_query.arun(query="Question")

        assert result == expected


@pytest.mark.asyncio
async def test_hermes_query_does_not_call_vault_write_or_approval_queue() -> None:
    with (
        patch(
            "app.agent.tools.builtin.hermes_query.query_recall",
            new=AsyncMock(return_value=HermesQueryResult(answer="No writes.")),
        ),
        patch("app.agent.tools.builtin.vault_write.vault_write.arun") as mock_write,
        patch("app.services.hermes_approval.get_hermes_approval_queue") as mock_queue,
    ):
        await hermes_query.arun(query="Question")

    mock_write.assert_not_called()
    mock_queue.assert_not_called()
