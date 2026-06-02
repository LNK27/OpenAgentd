"""Tests for Hermes pending approval built-in tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace.status import StatusCode

from app.agent.tools.builtin.hermes_pending import (
    hermes_pending_approve,
    hermes_pending_list,
    hermes_pending_reject,
)
from app.services import hermes_approval, vault_gatekeeper
from app.services.hermes import HermesIntentProposal
from app.services.vault_gatekeeper import VAULT_FOLDERS


@dataclass
class MockState:
    metadata: dict[str, str]


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
    monkeypatch.setattr(hermes_approval, "_default_queue", None)
    return target


def _state(session_id: str = "session-a", agent_name: str = "lead") -> MockState:
    return MockState(metadata={"session_id": session_id, "agent_name": agent_name})


def _intent(slug: str = "agent-memory") -> HermesIntentProposal:
    return HermesIntentProposal(
        folder="20-topics",
        slug=slug,
        title="Agent Memory",
        note_type="topic",
        body="Persistent memory.",
        tags=["memory"],
    )


@pytest.mark.asyncio
async def test_hermes_pending_list_formats_pending_entries() -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("one")])

    result = await hermes_pending_list.arun(_injected={"_state": _state()})

    assert enqueued.entries[0].pending_id in result
    assert "20-topics/one.md" in result
    assert "status: pending" in result


@pytest.mark.asyncio
async def test_hermes_pending_list_records_observability() -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    await queue.enqueue("session-a", [_intent("one")])
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool hermes_pending_list"):
        result = await hermes_pending_list.arun(_injected={"_state": _state()})

    assert "20-topics/one.md" in result
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.tool"] == "hermes_pending_list"
    assert span.attributes["openagentd.second_brain.outcome"] == "listed"
    assert span.attributes["hermes.pending_count"] == 1


@pytest.mark.asyncio
async def test_hermes_pending_approve_writes_note_successfully(
    _vault_dir: Path,
) -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("approved")])

    result = await hermes_pending_approve.arun(
        pending_id=enqueued.entries[0].pending_id,
        _injected={"_state": _state(agent_name="approver")},
    )

    assert (
        result == "Hermes pending intent approved and written to 20-topics/approved.md"
    )
    note = (_vault_dir / "20-topics" / "approved.md").read_text(encoding="utf-8")
    assert "writer: agent:approver" in note


@pytest.mark.asyncio
async def test_hermes_pending_approve_records_observability(
    _vault_dir: Path,
) -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("approved")])
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool hermes_pending_approve"):
        result = await hermes_pending_approve.arun(
            pending_id=enqueued.entries[0].pending_id,
            _injected={"_state": _state(agent_name="approver")},
        )

    assert "written to 20-topics/approved.md" in result
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.outcome"] == "approved"
    assert span.attributes["vault.path"] == "20-topics/approved.md"


@pytest.mark.asyncio
async def test_hermes_pending_reject_marks_rejected() -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("reject-me")])

    result = await hermes_pending_reject.arun(
        pending_id=enqueued.entries[0].pending_id,
        reason="not useful",
        _injected={"_state": _state()},
    )

    assert result == "Hermes pending intent rejected: reject-me"
    pending = await queue.list_pending("session-a")
    assert pending == []


@pytest.mark.asyncio
async def test_hermes_pending_reject_records_observability() -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("reject-me")])
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool hermes_pending_reject"):
        result = await hermes_pending_reject.arun(
            pending_id=enqueued.entries[0].pending_id,
            reason="not useful",
            _injected={"_state": _state()},
        )

    assert result == "Hermes pending intent rejected: reject-me"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.outcome"] == "rejected"
    assert span.attributes["vault.path"] == "20-topics/reject-me.md"


@pytest.mark.asyncio
async def test_pending_tools_require_session_id() -> None:
    state = MockState(metadata={})
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool hermes_pending_list"):
        result = await hermes_pending_list.arun(_injected={"_state": state})

    assert result == "Hermes approval queue requires a session_id."
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["openagentd.second_brain.outcome"] == "missing_session"


@pytest.mark.asyncio
async def test_hermes_pending_approve_returns_specific_write_error(
    _vault_dir: Path,
) -> None:
    queue = hermes_approval.get_hermes_approval_queue()
    enqueued = await queue.enqueue("session-a", [_intent("existing")])
    (_vault_dir / "20-topics" / "existing.md").write_text("original", encoding="utf-8")

    result = await hermes_pending_approve.arun(
        pending_id=enqueued.entries[0].pending_id,
        _injected={"_state": _state()},
    )

    assert (
        result
        == "Hermes approval failed: Note already exists at vault/20-topics/existing.md"
    )


def _tracer_with_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter
