"""Tests for ``AgentTeam.handle_continue`` and ``ContinuePreconditionError``.

Covers:

* Happy path — last message is an assistant turn; ``handle_continue`` runs
  the agent (with ``ContinuationHook``) against existing history,
  no new user row is persisted, and the new assistant row carries
  ``extra["is_continuation"] = True``.
* Precondition failures — empty session, last message is a user message,
  last assistant message has unfinished ``tool_calls``, last assistant
  message has empty content.
* Lead-busy guard — ``state == "working"`` rejects continuation.

These tests exercise the **real** DB via the in-memory engine wired up in
``tests/conftest.py`` so the ``get_messages``-driven precondition checks
run against actual persisted rows.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent.agent_loop import Agent
from app.agent.hooks.continuation import CONTINUATION_DIRECTIVE, ContinuationHook
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam, ContinuePreconditionError
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.state import AgentState, ModelRequest, RunContext
from app.models.chat import ChatSession, SessionMessage
from tests.agent.mode.team.conftest import MockTeamProvider


# ─────────────────────────────────────────────────────────────────────────────
# ContinuationHook unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestContinuationHookStamp:
    """``after_model`` should stamp the first assistant message and only that."""

    @pytest.mark.asyncio
    async def test_stamps_first_assistant_message(self):
        hook = ContinuationHook()
        ctx = RunContext(session_id="s1", agent_name="lead", run_id="r1")
        state = AgentState(messages=[])
        msg = AssistantMessage(content="hello")

        await hook.after_model(ctx, state, msg)

        assert msg.extra == {"is_continuation": True}

    @pytest.mark.asyncio
    async def test_merges_into_existing_extra(self):
        """Must not clobber the ``usage`` dict set by the agent loop."""
        hook = ContinuationHook()
        ctx = RunContext(session_id="s1", agent_name="lead", run_id="r1")
        state = AgentState(messages=[])
        msg = AssistantMessage(content="hello", extra={"usage": {"input": 100}})

        await hook.after_model(ctx, state, msg)

        assert msg.extra == {"usage": {"input": 100}, "is_continuation": True}

    @pytest.mark.asyncio
    async def test_only_fires_once(self):
        """Subsequent assistant messages in the same run must NOT be stamped."""
        hook = ContinuationHook()
        ctx = RunContext(session_id="s1", agent_name="lead", run_id="r1")
        state = AgentState(messages=[])
        first = AssistantMessage(content="part 1")
        second = AssistantMessage(content="part 2", extra={"usage": {"input": 50}})

        await hook.after_model(ctx, state, first)
        await hook.after_model(ctx, state, second)

        assert first.extra == {"is_continuation": True}
        # Second message keeps its own extra, no is_continuation flag.
        assert second.extra == {"usage": {"input": 50}}


class TestContinuationHookDirective:
    """``before_model`` should append the ephemeral directive once per run."""

    @pytest.mark.asyncio
    async def test_appends_directive_humanmessage(self):
        hook = ContinuationHook()
        ctx = RunContext(session_id="s1", agent_name="lead", run_id="r1")
        state = AgentState(messages=[])
        base = ModelRequest(
            messages=(
                HumanMessage(content="write a poem"),
                AssistantMessage(content="Roses are"),
            ),
            system_prompt="be helpful",
        )

        out = await hook.before_model(ctx, state, base)

        assert out is not None
        # Original messages preserved, directive appended at the end as user.
        assert len(out.messages) == 3
        assert out.messages[0] is base.messages[0]
        assert out.messages[1] is base.messages[1]
        appended = out.messages[2]
        assert isinstance(appended, HumanMessage)
        assert appended.content == CONTINUATION_DIRECTIVE
        # System prompt is unchanged — the directive is conveyed via the
        # message list, not by mutating the system prompt.
        assert out.system_prompt == base.system_prompt

    @pytest.mark.asyncio
    async def test_directive_only_fires_once(self):
        """Subsequent ``before_model`` calls in the same run return None."""
        hook = ContinuationHook()
        ctx = RunContext(session_id="s1", agent_name="lead", run_id="r1")
        state = AgentState(messages=[])
        req = ModelRequest(
            messages=(AssistantMessage(content="partial"),),
            system_prompt="",
        )

        first = await hook.before_model(ctx, state, req)
        second = await hook.before_model(ctx, state, req)

        assert first is not None
        assert second is None


# ─────────────────────────────────────────────────────────────────────────────
# AgentTeam.handle_continue — precondition tests (no agent.run involved)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def lead_only_team():
    """Team with one lead and no members — minimum surface for continue tests."""
    lead = TeamLead(Agent(name="lead", llm_provider=MockTeamProvider("ok")))
    return AgentTeam(lead=lead, members={})


async def _seed_session(session_id: uuid.UUID, *, agent_name: str = "lead") -> None:
    """Insert a bare ChatSession row for *session_id*."""
    import app.core.db as _db

    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(ChatSession(id=session_id, agent_name=agent_name))


async def _seed_message(
    session_id: uuid.UUID,
    role: str,
    content: str | None,
    *,
    tool_calls: list[dict] | None = None,
) -> None:
    """Insert a single ``SessionMessage`` row."""
    import app.core.db as _db

    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(
                SessionMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                )
            )


class TestHandleContinuePreconditions:
    @pytest.mark.asyncio
    async def test_rejects_unknown_session(self, lead_only_team):
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(uuid.uuid7()))
        assert exc_info.value.status == 409
        assert "not found" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_empty_session(self, lead_only_team):
        sid = uuid.uuid7()
        await _seed_session(sid)
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(sid))
        assert exc_info.value.status == 409
        assert "no messages" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_session_owned_by_other_agent(self, lead_only_team):
        """Ownership guard — refuse to continue a session whose ChatSession.agent_name
        does not match the lead's name."""
        sid = uuid.uuid7()
        await _seed_session(sid, agent_name="some_other_agent")
        # Even with valid assistant content, the ownership check must fire
        # before we examine the message list.
        await _seed_message(sid, role="user", content="hi")
        await _seed_message(sid, role="assistant", content="partial answer")
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(sid))
        assert exc_info.value.status == 409
        assert "belongs to" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_last_message_is_user(self, lead_only_team):
        sid = uuid.uuid7()
        await _seed_session(sid)
        await _seed_message(sid, role="user", content="hello")
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(sid))
        assert exc_info.value.status == 409
        assert "not an assistant message" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_last_assistant_has_tool_calls(self, lead_only_team):
        sid = uuid.uuid7()
        await _seed_session(sid)
        await _seed_message(sid, role="user", content="run shell")
        await _seed_message(
            sid,
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "shell", "arguments": "{}"},
                }
            ],
        )
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(sid))
        assert exc_info.value.status == 409
        assert "tool call" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_last_assistant_has_empty_content(self, lead_only_team):
        sid = uuid.uuid7()
        await _seed_session(sid)
        await _seed_message(sid, role="user", content="hi")
        await _seed_message(sid, role="assistant", content="   ")
        with pytest.raises(ContinuePreconditionError) as exc_info:
            await lead_only_team.handle_continue(str(sid))
        assert exc_info.value.status == 409
        assert "no content" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_lead_is_working(self, lead_only_team):
        sid = uuid.uuid7()
        await _seed_session(sid)
        await _seed_message(sid, role="user", content="hi")
        await _seed_message(sid, role="assistant", content="working on it")

        lead_only_team.lead.state = "working"
        try:
            with pytest.raises(ContinuePreconditionError) as exc_info:
                await lead_only_team.handle_continue(str(sid))
            assert "working" in exc_info.value.reason.lower()
        finally:
            lead_only_team.lead.state = "idle"


# ─────────────────────────────────────────────────────────────────────────────
# AgentTeam.handle_continue — happy path: full activation roundtrip
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_continue_happy_path_stamps_assistant_row(monkeypatch):
    """End-to-end: seed session ending in a partial assistant message,
    run handle_continue, verify a new assistant row appears with
    ``extra.is_continuation == True`` and no extra user row was added.
    """
    import app.core.db as _db

    sid = uuid.uuid7()
    await _seed_session(sid)
    await _seed_message(sid, role="user", content="count to 10")
    await _seed_message(sid, role="assistant", content="1, 2, 3, 4,")

    # Provider that produces a deterministic completion delta.
    provider = MockTeamProvider("5, 6, 7, 8, 9, 10")
    lead = TeamLead(
        Agent(name="lead", llm_provider=provider),
        session_id=str(sid),
        db_factory=_db.async_session_factory,
    )
    team = AgentTeam(lead=lead, members={})
    # Bind the team so the lead has a mailbox (used by activation).
    await team.start()

    try:
        returned_sid = await team.handle_continue(str(sid))
        assert returned_sid == str(sid)

        # Wait for the activation task to complete.
        for _ in range(50):
            await asyncio.sleep(0.02)
            task = lead._active_task
            if task is None or task.done():
                break
        # If the run errored, fail loudly with the traceback.
        if lead._active_task is not None and lead._active_task.done():
            exc = lead._active_task.exception()
            assert exc is None, f"activation task failed: {exc!r}"

        # Verify DB state.
        async with _db.async_session_factory() as db:
            from sqlmodel import col, select

            stmt = (
                select(SessionMessage)
                .where(col(SessionMessage.session_id) == sid)
                .order_by(col(SessionMessage.created_at))
            )
            rows = (await db.exec(stmt)).all()

        roles = [r.role for r in rows]
        # Expected: original [user, assistant] + one new assistant from continue.
        assert roles == ["user", "assistant", "assistant"], (
            f"unexpected roles in DB: {roles}"
        )
        # The new assistant row must carry the continuation flag.
        new_assistant = rows[-1]
        assert new_assistant.content == "5, 6, 7, 8, 9, 10"
        assert new_assistant.extra is not None
        assert new_assistant.extra.get("is_continuation") is True

        # And no extra user row was created.
        assert sum(1 for r in rows if r.role == "user") == 1
    finally:
        await team.stop()
