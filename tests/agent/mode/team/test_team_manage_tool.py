"""Tests for team_configure tool — session-local member capability management.

Covers:
- Lead-only injection (members do not get the tool)
- list / add / remove flow against live member instances
- Idempotency (add already-present, remove not-present)
- Validation (unknown skill / tool / mcp / member)
- Protected tool names (skill, team_message, lead-only tools) cannot be granted
- Lead is not a manageable target
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from app.agent.agent_loop import Agent
from app.agent.drift import stamp_agent_files
from app.agent.loader import load_team_from_dir, parse_agent_md
from app.agent.mode.team.manage import make_team_configure_tool
from app.agent.mode.team.member import TeamLead, TeamMember
from app.agent.mode.team.team import AgentTeam


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_member_md(
    path: Path,
    *,
    name: str,
    skills: list[str] | None = None,
    tools: list[str] | None = None,
    mcp: list[str] | None = None,
) -> Path:
    """Write a minimal valid member .md file at *path* and return the path."""
    meta: dict = {"name": name, "role": "member", "model": "mock:model"}
    if skills is not None:
        meta["skills"] = skills
    if tools is not None:
        meta["tools"] = tools
    if mcp is not None:
        meta["mcp"] = mcp
    yaml_block = yaml.safe_dump(meta, sort_keys=False).strip()
    body = f"---\n{yaml_block}\n---\nYou are {name}.\n"
    path.write_text(body, encoding="utf-8")
    return path


def _make_team_with_file_backed_member(
    tmp_path: Path,
    *,
    member_name: str = "executor",
    skills: list[str] | None = None,
    tools: list[str] | None = None,
    mcp: list[str] | None = None,
) -> tuple[AgentTeam, Path]:
    """Construct a 1-lead-1-member team where the member's agent has a real source_path."""
    from tests.agent.mode.team.conftest import MockTeamProvider

    member_md = _write_member_md(
        tmp_path / f"{member_name}.md",
        name=member_name,
        skills=skills,
        tools=tools,
        mcp=mcp,
    )

    lead_agent = Agent(name="lead", llm_provider=MockTeamProvider("ok"))
    lead = TeamLead(lead_agent)

    member_agent = Agent(name=member_name, llm_provider=MockTeamProvider("ok"))
    if tools:
        from app.agent.loader import _default_tool_registry

        registry = _default_tool_registry()
        member_agent._tools = {
            name: registry[name] for name in tools if name in registry
        }
    member_agent.source_path = member_md
    member_agent.skills = list(skills or [])
    member_agent.mcp_servers = list(mcp or [])
    member = TeamMember(member_agent)

    team = AgentTeam(lead=lead, members={member_name: member})
    return team, member_md


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


class TestTeamConfigureInjection:
    """Lead-only injection."""

    async def test_lead_gets_team_configure(self, basic_team):
        injected = basic_team.get_injected_tools(basic_team.lead.name)
        names = {t.name for t in injected}
        assert "team_configure" in names
        assert "team_message" in names
        assert "todo_manage" in names

    async def test_member_does_not_get_team_configure(self, basic_team):
        injected = basic_team.get_injected_tools("member_a")
        names = {t.name for t in injected}
        assert "team_configure" not in names
        assert "team_message" in names
        assert "todo_manage" in names


# ---------------------------------------------------------------------------
# list action
# ---------------------------------------------------------------------------


class TestTeamConfigureList:
    async def test_list_reads_live_member(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(
            tmp_path,
            skills=["example-skill"],
            tools=["read"],
            mcp=["context7"],
        )
        tool = make_team_configure_tool(team)

        result = await tool(member="executor", action="list")

        assert "example-skill" in result
        assert "read" in result
        assert "context7" in result

    async def test_list_includes_effective_builtin_capabilities(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path, tools=[])
        member = team.members["executor"]
        member.agent._tools = {"shell": object()}  # built-in runtime capability
        tool = make_team_configure_tool(team)

        result = await tool(member="executor", action="list")

        assert "shell" in result

    async def test_list_unknown_member(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path)
        tool = make_team_configure_tool(team)

        result = await tool(member="ghost", action="list")

        assert "not found" in result
        assert "executor" in result  # available members listed


# ---------------------------------------------------------------------------
# add action
# ---------------------------------------------------------------------------


class TestTeamConfigureAdd:
    async def test_add_skill_updates_live_member_only(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, skills=[])
        tool = make_team_configure_tool(team)

        with patch(
            "app.agent.tools.builtin.skill.discover_skills",
            return_value={"example-skill": {}},
        ):
            result = await tool(
                member="executor",
                action="add",
                kind="skill",
                name="example-skill",
            )

        assert "Added" in result
        assert "example-skill" in team.members["executor"].agent.skills
        assert "example-skill" not in parse_agent_md(md).skills

    async def test_add_mcp_updates_live_member_only(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, mcp=[])
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            result = await tool(
                member="executor",
                action="add",
                kind="mcp",
                name="shadcn",
            )

        assert "Added" in result
        assert "shadcn" in team.members["executor"].agent.mcp_servers
        assert "shadcn" not in parse_agent_md(md).mcp

    async def test_add_mcp_attaches_server_tools_to_live_member(self, tmp_path):
        from app.agent.tools.registry import Tool

        def fn():
            return "ok"

        server_tool = Tool(fn, name="mcp_shadcn_get_component")
        team, md = _make_team_with_file_backed_member(tmp_path, mcp=[])
        agent = team.members["executor"].agent
        tool = make_team_configure_tool(team)

        with (
            patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]),
            patch(
                "app.agent.mcp.mcp_manager.get_tools_for_server",
                return_value=[server_tool],
            ),
        ):
            result = await tool(
                member="executor", action="add", kind="mcp", name="shadcn"
            )

        assert "Added" in result
        assert agent.mcp_servers == ["shadcn"]
        assert agent._tools["mcp_shadcn_get_component"] is server_tool
        assert parse_agent_md(md).mcp == []

    async def test_add_tool_updates_live_member_only(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, tools=[])
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor",
            action="add",
            kind="tool",
            name="web_search",
        )

        assert "Added" in result
        assert "web_search" in team.members["executor"].agent._tools
        assert "web_search" not in parse_agent_md(md).tools

    async def test_add_tool_does_not_replace_existing_live_tool(self, tmp_path):
        from app.agent.tools.registry import Tool

        def fn():
            return "custom"

        existing = Tool(fn, name="web_search")
        team, md = _make_team_with_file_backed_member(tmp_path, tools=[])
        agent = team.members["executor"].agent
        agent._tools["web_search"] = existing
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor", action="add", kind="tool", name="web_search"
        )

        assert "already" in result.lower()
        assert agent._tools["web_search"] is existing
        assert parse_agent_md(md).tools == []

    async def test_add_already_present_is_idempotent(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, mcp=["shadcn"])
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            result = await tool(
                member="executor",
                action="add",
                kind="mcp",
                name="shadcn",
            )

        assert "already" in result.lower()
        # File still parses, list unchanged
        cfg = parse_agent_md(md)
        assert cfg.mcp == ["shadcn"]


# ---------------------------------------------------------------------------
# remove action
# ---------------------------------------------------------------------------


class TestTeamConfigureRemove:
    async def test_remove_mcp_updates_live_member_only(self, tmp_path):
        team, md = _make_team_with_file_backed_member(
            tmp_path, mcp=["shadcn", "context7"]
        )
        tool = make_team_configure_tool(team)

        with patch(
            "app.agent.mcp.mcp_manager.server_names",
            return_value=["shadcn", "context7"],
        ):
            result = await tool(
                member="executor",
                action="remove",
                kind="mcp",
                name="shadcn",
            )

        assert "Removed" in result
        assert "shadcn" not in team.members["executor"].agent.mcp_servers
        assert "context7" in team.members["executor"].agent.mcp_servers
        assert parse_agent_md(md).mcp == ["shadcn", "context7"]

    async def test_remove_not_present_is_idempotent(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, skills=[])
        tool = make_team_configure_tool(team)

        with patch(
            "app.agent.tools.builtin.skill.discover_skills",
            return_value={"example-skill": {}},
        ):
            result = await tool(
                member="executor",
                action="remove",
                kind="skill",
                name="example-skill",
            )

        assert "not enabled" in result
        cfg = parse_agent_md(md)
        assert cfg.skills == []

    async def test_remove_tool_removes_live_tool_only(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, tools=["web_search"])
        agent = team.members["executor"].agent
        assert "web_search" in agent._tools
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor", action="remove", kind="tool", name="web_search"
        )

        assert "Removed" in result
        assert "web_search" not in agent._tools
        assert parse_agent_md(md).tools == ["web_search"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestTeamConfigureValidation:
    async def test_unknown_skill_rejected(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path)
        before = list(team.members["executor"].agent.skills)
        tool = make_team_configure_tool(team)

        with patch(
            "app.agent.tools.builtin.skill.discover_skills",
            return_value={"example-skill": {}},
        ):
            result = await tool(
                member="executor",
                action="add",
                kind="skill",
                name="nope",
            )

        assert "Unknown skill" in result
        assert team.members["executor"].agent.skills == before

    async def test_unknown_tool_rejected(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path)
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor",
            action="add",
            kind="tool",
            name="not_a_real_tool",
        )

        assert "Unknown tool" in result

    async def test_unknown_mcp_rejected(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path)
        before = list(team.members["executor"].agent.mcp_servers)
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            result = await tool(
                member="executor",
                action="add",
                kind="mcp",
                name="missing",
            )

        assert "Unknown MCP server" in result
        assert team.members["executor"].agent.mcp_servers == before

    async def test_protected_tool_rejected(self, tmp_path):
        """Always-on / lead-only tools cannot be granted."""
        team, _ = _make_team_with_file_backed_member(tmp_path)
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor",
            action="add",
            kind="tool",
            name="todo_manage",
        )

        assert "protected" in result.lower()

    async def test_lead_is_not_a_target(self, tmp_path):
        """The lead cannot be managed via team_configure."""
        team, _ = _make_team_with_file_backed_member(tmp_path)
        tool = make_team_configure_tool(team)

        result = await tool(
            member="lead",
            action="list",
        )

        assert "not found" in result

    async def test_in_memory_member_can_be_managed(self, basic_team):
        """team_configure is session-local and does not require source_path."""
        tool = make_team_configure_tool(basic_team)

        result = await tool(member="member_a", action="list")

        assert "Capabilities for live member" in result

    async def test_add_without_kind_or_name(self, tmp_path):
        team, _ = _make_team_with_file_backed_member(tmp_path)
        tool = make_team_configure_tool(team)

        result = await tool(member="executor", action="add")

        assert "kind" in result and "name" in result


# ---------------------------------------------------------------------------
# Session-local semantics
# ---------------------------------------------------------------------------


class TestTeamConfigureSessionLocal:
    async def test_add_does_not_write_member_file(self, tmp_path):
        team, md = _make_team_with_file_backed_member(tmp_path, mcp=[])
        before = md.read_text()
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            result = await tool(
                member="executor", action="add", kind="mcp", name="shadcn"
            )

        assert "current team session" in result
        assert team.members["executor"].agent.mcp_servers == ["shadcn"]
        assert md.read_text() == before

    async def test_list_reflects_live_changes(self, tmp_path):
        team, _md = _make_team_with_file_backed_member(tmp_path, mcp=[])
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            await tool(member="executor", action="add", kind="mcp", name="shadcn")
            result = await tool(member="executor", action="list")

        assert "shadcn" in result

    async def test_remove_mcp_removes_owned_mcp_tools_from_live_member(self, tmp_path):
        from app.agent.tools.registry import Tool

        def fn():
            return "ok"

        team, _md = _make_team_with_file_backed_member(tmp_path, mcp=["shadcn"])
        agent = team.members["executor"].agent
        agent._tools["mcp_shadcn_get_component"] = Tool(
            fn, name="mcp_shadcn_get_component"
        )
        agent._tools["read"] = Tool(fn, name="read")
        tool = make_team_configure_tool(team)

        with patch("app.agent.mcp.mcp_manager.server_names", return_value=["shadcn"]):
            result = await tool(
                member="executor", action="remove", kind="mcp", name="shadcn"
            )

        assert "Removed" in result
        assert "shadcn" not in agent.mcp_servers
        assert "mcp_shadcn_get_component" not in agent._tools
        assert "read" in agent._tools

    async def test_runtime_tool_grant_is_reset_by_dismiss_and_respawn(self, tmp_path):
        from tests.agent.mode.team.conftest import MockTeamProvider

        _write_member_md(tmp_path / "lead.md", name="lead")
        lead_text = (tmp_path / "lead.md").read_text(encoding="utf-8")
        (tmp_path / "lead.md").write_text(
            lead_text.replace("role: member", "role: lead"), encoding="utf-8"
        )
        _write_member_md(tmp_path / "executor.md", name="executor", tools=[])

        team = load_team_from_dir(
            tmp_path,
            provider_factory=lambda *_args, **_kwargs: MockTeamProvider("ok"),
        )
        assert team is not None
        member = await team.spawn("executor")
        tool = make_team_configure_tool(team)

        result = await tool(
            member=member.name, action="add", kind="tool", name="web_search"
        )
        assert "Added" in result
        assert "web_search" in team.members[member.name].agent._tools

        assert await team.dismiss(member.name) is True
        restored = await team.spawn("executor", instance_id=1)

        assert restored.name == member.name
        assert "web_search" not in restored.agent._tools

    async def test_runtime_tool_grant_is_reset_by_config_drift_reload(self, tmp_path):
        from tests.agent.mode.team.conftest import MockTeamProvider

        member_md = _write_member_md(
            tmp_path / "executor.md", name="executor", tools=[]
        )
        team, _ = _make_team_with_file_backed_member(tmp_path, tools=[])
        member = team.members["executor"]
        member.agent.llm_provider = MockTeamProvider("ok")
        member.agent.config_stamp = stamp_agent_files(
            agent_md_path=member_md,
            skill_names=[],
            skills_dir=tmp_path / "skills",
            mcp_config_path=tmp_path / "mcp.json",
        )
        tool = make_team_configure_tool(team)

        result = await tool(
            member="executor", action="add", kind="tool", name="web_search"
        )
        assert "Added" in result
        assert "web_search" in member.agent._tools

        before = member_md.read_text(encoding="utf-8")
        member_md.write_text(before + "\n<!-- drift -->\n", encoding="utf-8")

        assert member.refresh_if_dirty() is True
        assert "web_search" not in member.agent._tools
        assert member.agent.name == "executor"
