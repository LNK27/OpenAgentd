"""Tests for ``POST /team/commands`` — slash-command dispatch.

Covers the route layer only — the team-level behaviour is tested in
``tests/agent/mode/team/test_team_continue.py``.  These tests verify
the HTTP shape: response codes, response body, and that
``ContinuePreconditionError`` maps to a 409 with a usable ``detail``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

import app.core.db as _db
from app.agent.agent_loop import Agent
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam
from app.models.chat import ChatSession, SessionMessage
from tests.api.routes.test_team_db import MockProvider


@pytest_asyncio.fixture
async def app_with_lead_only_team():
    """App + a started team with one lead, no members.

    ``team.start()`` is awaited so the lead has a registered mailbox by the
    time ``handle_continue`` calls ``activate_for_continuation`` on the
    happy path — otherwise the spawned task hits
    ``assert self._mailbox is not None`` and the test leaks an orphan
    ``AssertionError``.
    """
    from app.api.app import create_app
    from app.services.team_manager import set_team

    lead = TeamLead(
        Agent(name="lead", llm_provider=MockProvider(), system_prompt="Lead"),
        db_factory=_db.async_session_factory,
    )
    team = AgentTeam(lead=lead, members={})
    await team.start()
    app = create_app()
    set_team(team)
    try:
        yield app
    finally:
        set_team(None)
        await team.stop()


async def _seed_session_and_messages(
    session_id: uuid.UUID,
    msgs: list[tuple[str, str | None, list[dict] | None]],
) -> None:
    """Seed a session + a list of ``(role, content, tool_calls)`` rows."""
    import app.core.db as _db

    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(ChatSession(id=session_id, agent_name="lead"))
            for role, content, tool_calls in msgs:
                db.add(
                    SessionMessage(
                        session_id=session_id,
                        role=role,
                        content=content,
                        tool_calls=tool_calls,
                    )
                )


class TestPostTeamCommands:
    @pytest.mark.asyncio
    async def test_continue_returns_409_for_unknown_session(
        self, app_with_lead_only_team
    ):
        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "continue", "session_id": str(uuid.uuid7())},
        )
        assert resp.status_code == 409
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_continue_returns_409_when_last_message_is_user(
        self, app_with_lead_only_team
    ):
        sid = uuid.uuid7()
        await _seed_session_and_messages(sid, [("user", "hello", None)])

        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "continue", "session_id": str(sid)},
        )
        assert resp.status_code == 409
        assert "not an assistant message" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_continue_returns_409_when_assistant_has_tool_calls(
        self, app_with_lead_only_team
    ):
        sid = uuid.uuid7()
        await _seed_session_and_messages(
            sid,
            [
                ("user", "run shell", None),
                (
                    "assistant",
                    "",
                    [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }
                    ],
                ),
            ],
        )

        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "continue", "session_id": str(sid)},
        )
        assert resp.status_code == 409
        assert "tool call" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_continue_returns_202_on_happy_path(self, app_with_lead_only_team):
        """Happy path returns 202 + session_id; activation runs in background.

        The actual streaming behaviour is tested in
        ``test_team_continue.py::test_handle_continue_happy_path_stamps_assistant_row``.
        Here we only assert the route's HTTP contract.
        """
        sid = uuid.uuid7()
        await _seed_session_and_messages(
            sid,
            [
                ("user", "count to 10", None),
                ("assistant", "1, 2, 3, 4,", None),
            ],
        )

        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "continue", "session_id": str(sid)},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["session_id"] == str(sid)
        assert body["command"] == "continue"

    @pytest.mark.asyncio
    async def test_compact_returns_202_on_happy_path(self, app_with_lead_only_team):
        sid = uuid.uuid7()
        await _seed_session_and_messages(
            sid,
            [
                ("user", "first", None),
                ("assistant", "first answer", None),
                ("user", "second", None),
                ("assistant", "second answer", None),
                ("user", "third", None),
                ("assistant", "third answer", None),
            ],
        )

        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "compact", "session_id": str(sid)},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["session_id"] == str(sid)
        assert body["command"] == "compact"

    @pytest.mark.asyncio
    async def test_unknown_command_rejected_by_validator(self, app_with_lead_only_team):
        """Pydantic Literal rejects unknown command strings as 422."""
        client = TestClient(app_with_lead_only_team)
        resp = client.post(
            "/api/team/commands",
            json={"command": "blow_up_session", "session_id": str(uuid.uuid7())},
        )
        assert resp.status_code == 422
