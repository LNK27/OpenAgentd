"""Team lifecycle manager.

Teams are loaded lazily on first use and evicted after an idle window.

Usage::

    team_manager.validate_agents_dir()               # startup (parse-only)
    team = await team_manager.get_or_start_team()    # on demand
    await team_manager.stop()                        # shutdown

Lazy lifecycle
--------------

The default team (and per-workspace coding teams) are not built on
server startup.  ``get_or_start_team()`` and ``get_or_start_coding_team()``
build them on the first incoming request (chat, scheduler fire,
``/team/agents``, etc.) and cache them in module state.

After an idle window with no working members, teams are evicted on the
next ``get_or_start_*`` call:

* Default team — ``_DEFAULT_TEAM_IDLE_SECONDS`` (1 hour)
* Coding teams — ``_CODING_TEAM_IDLE_SECONDS`` (30 minutes)

Eviction is opportunistic (no background timer); the cost of an
evicted-then-re-requested team is one ``load_team_from_dir`` + ``team.start()``
on the next request (~10–100 ms), which is below user-perceptible
latency on a chat send.

Live-config refresh — no team reload
------------------------------------

Agents now refresh themselves at the start of their next turn when
their tracked config files (their own ``.md``, ``mcp.json``, referenced
``SKILL.md``) change on disk.  See ``app.agent.loader.stamp_agent_files``
and ``TeamMemberBase._detect_config_drift``.  Production code paths
(``/api/mcp``, ``/api/skills``, ``/api/agents``) therefore do **not**
call :func:`reload`.

:func:`reload` is retained as a legacy admin tool for operational forced
rebuilds and as a hook for tests; do not call it from request handlers.
It rebuilds the entire team — stopping in-flight agents and rotating
session IDs — which is exactly what the live-config mechanism was
introduced to avoid.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.loader import load_team_from_dir
from app.core.config import settings

if TYPE_CHECKING:
    from app.agent.mode.team.team import AgentTeam


# ── Diff dataclass ───────────────────────────────────────────────────────────


@dataclass
class TeamDiff:
    """Difference between the previous and new team after a reload."""

    added: list[str]  # agent names added
    removed: list[str]  # agent names removed
    changed: list[str]  # agent names where model / tools / skills changed
    lead: str  # name of the new lead
    members: list[str]  # names of all members (excluding lead)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "lead": self.lead,
            "members": self.members,
        }


# ── Module-level state ───────────────────────────────────────────────────────

_team: "AgentTeam | None" = None
_team_last_used: float = 0.0
_coding_teams: dict[str, "AgentTeam"] = {}
_coding_team_last_used: dict[str, float] = {}
_DEFAULT_TEAM_IDLE_SECONDS = 60 * 60
_CODING_TEAM_IDLE_SECONDS = 30 * 60
_lock = asyncio.Lock()


def _resolve_agents_dir() -> Path:
    path = Path(settings.AGENTS_DIR)
    return path if path.is_absolute() else Path.cwd() / path


def _resolve_coding_agents_dir() -> Path:
    return _resolve_agents_dir() / "coding"


def _resolve_workspace(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def validate_workspace(workspace: str) -> str:
    resolved = _resolve_workspace(workspace)
    if not resolved.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {resolved}")
    return str(resolved)


def _team_is_idle(team: "AgentTeam") -> bool:
    return all(member.state != "working" for member in team.all_members)


# Back-compat alias — older call sites (tests) may import the coding-specific name.
_coding_team_is_idle = _team_is_idle


def _maybe_pop_idle_default_team_locked(
    now: float,
) -> "AgentTeam | None":
    """Return the default team for eviction, or ``None`` if it should stay.

    Caller must release the lock before stopping the returned team to avoid
    holding ``_lock`` across the team's shutdown work.
    """
    global _team, _team_last_used
    if _team is None:
        return None
    if now - _team_last_used <= _DEFAULT_TEAM_IDLE_SECONDS:
        return None
    if not _team_is_idle(_team):
        return None
    expired = _team
    _team = None
    _team_last_used = 0.0
    return expired


def _pop_idle_coding_teams_locked(now: float) -> list[tuple[str, "AgentTeam"]]:
    expired = [
        workspace
        for workspace, last_used in _coding_team_last_used.items()
        if now - last_used > _CODING_TEAM_IDLE_SECONDS
        and (team := _coding_teams.get(workspace)) is not None
        and _coding_team_is_idle(team)
    ]
    popped: list[tuple[str, "AgentTeam"]] = []
    for workspace in expired:
        team = _coding_teams.pop(workspace, None)
        _coding_team_last_used.pop(workspace, None)
        if team is not None:
            popped.append((workspace, team))
    return popped


async def _stop_coding_teams(teams: list[tuple[str, "AgentTeam"]]) -> None:
    for workspace, team in teams:
        try:
            await team.stop()
        except Exception:
            logger.exception("coding_team_idle_stop_error workspace={}", workspace)
        else:
            logger.info("coding_team_idle_stopped workspace={}", workspace)


def current_team() -> "AgentTeam | None":
    return _team


def current_team_for_workspace(workspace: str | None) -> "AgentTeam | None":
    if not workspace:
        return _team
    return _coding_teams.get(str(_resolve_workspace(workspace)))


def set_team(team: "AgentTeam | None") -> None:
    """Replace the current team reference without running the lifecycle.

    Intended for tests that need to inject a pre-built ``AgentTeam`` into
    the FastAPI dependency without starting the real team.  Production
    code should use :func:`get_or_start_team` / :func:`reload` / :func:`stop`.
    """
    global _team, _team_last_used
    _team = team
    _team_last_used = time.monotonic() if team is not None else 0.0


# ── Lifecycle ────────────────────────────────────────────────────────────────


def validate_agents_dir() -> bool:
    """Parse-only check that the agents directory is loadable.

    Called from the FastAPI lifespan at startup so a malformed config
    surfaces immediately (server fails to boot) instead of on the first
    chat request.  Does **not** build or cache an ``AgentTeam`` — that
    happens lazily on the first call to :func:`get_or_start_team`.

    Returns ``True`` when the directory contains a valid lead, ``False``
    when it is empty or missing.  Re-raises ``ValueError`` from the loader
    on parse errors.
    """
    agents_dir = _resolve_agents_dir()
    try:
        team = load_team_from_dir(agents_dir)
    except ValueError:
        raise
    if team is None:
        logger.warning("team_manager_agents_dir_empty path={}", agents_dir)
        return False
    logger.info(
        "team_manager_agents_dir_validated path={} lead={}", agents_dir, team.lead.name
    )
    return True


async def get_or_start_team() -> "AgentTeam | None":
    """Return the cached default team, building it on first use.

    Evicts the cached team if it has been idle for longer than
    ``_DEFAULT_TEAM_IDLE_SECONDS`` and has no working members.  Returns
    ``None`` when the agents directory is empty or missing (mirroring
    the legacy ``start()`` behaviour so callers can render a friendly
    "no agents configured" response).
    """
    global _team, _team_last_used

    async with _lock:
        now = time.monotonic()
        expired = _maybe_pop_idle_default_team_locked(now)

        if _team is not None:
            _team_last_used = now
            result: "AgentTeam | None" = _team
        else:
            agents_dir = _resolve_agents_dir()
            candidate = load_team_from_dir(agents_dir)
            if candidate is None:
                logger.warning("team_manager_no_agents path={}", agents_dir)
                result = None
            else:
                await candidate.start()
                _team = candidate
                _team_last_used = now
                logger.info("team_manager_started lead={}", candidate.lead.name)
                result = candidate

    if expired is not None:
        try:
            await expired.stop()
        except Exception:
            logger.exception("team_manager_idle_stop_error")
        else:
            logger.info("team_manager_idle_stopped")

    return result


async def stop() -> None:
    """Stop the current team (if any) on server shutdown."""
    global _team, _team_last_used
    async with _lock:
        if _team is not None:
            try:
                await _team.stop()
            except Exception:
                logger.exception("team_manager_stop_error")
            _team = None
            _team_last_used = 0.0
        for workspace, team in list(_coding_teams.items()):
            try:
                await team.stop()
            except Exception:
                logger.exception(
                    "coding_team_manager_stop_error workspace={}", workspace
                )
        _coding_teams.clear()
        _coding_team_last_used.clear()


async def get_or_start_coding_team(workspace: str) -> "AgentTeam":
    key = validate_workspace(workspace)
    async with _lock:
        now = time.monotonic()
        expired = _pop_idle_coding_teams_locked(now)
        existing = _coding_teams.get(key)
        if existing is not None:
            _coding_team_last_used[key] = now
            team = existing
        else:
            agents_dir = _resolve_coding_agents_dir()
            team = load_team_from_dir(agents_dir, mode="coding", workspace=key)
            if team is None:
                raise ValueError(
                    f"No coding agents found in '{agents_dir}'. "
                    "Create at least one .md file with 'role: lead'."
                )
            await team.start()
            _coding_teams[key] = team
            _coding_team_last_used[key] = now
            logger.info("coding_team_started workspace={} lead={}", key, team.lead.name)

    await _stop_coding_teams(expired)
    return team


# ── Hot reload ───────────────────────────────────────────────────────────────


def _team_snapshot(team: "AgentTeam") -> dict[str, dict]:
    """Capture per-agent fingerprint used to compute the diff."""
    snapshot: dict[str, dict] = {}
    members = [team.lead, *team.members.values()]
    for m in members:
        agent = m.agent
        snapshot[agent.name] = {
            "description": agent.description or "",
            "model": agent.model_id,
            "tools": sorted(t.name for t in agent._tools.values()),
            "skills": sorted(agent.skills or []),
            "system_prompt": agent.system_prompt,
        }
    return snapshot


def _compute_diff(before: dict[str, dict] | None, team: "AgentTeam") -> TeamDiff:
    after = _team_snapshot(team)
    before = before or {}

    before_names = set(before.keys())
    after_names = set(after.keys())

    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)
    changed = sorted(
        name for name in before_names & after_names if before[name] != after[name]
    )

    members = sorted(team.members.keys())
    return TeamDiff(
        added=added,
        removed=removed,
        changed=changed,
        lead=team.lead.name,
        members=members,
    )


async def reload() -> TeamDiff:
    """Rebuild the team from ``AGENTS_DIR`` and atomically swap it in.

    .. warning::
        Legacy admin path.  Calling this stops every agent (cancelling
        any in-flight tool execution, rotating session IDs, emitting a
        premature ``done`` event for the active turn).  Production code
        should rely on the live-config refresh mechanism instead — see
        the module docstring.

    Raises ``ValueError`` (from :func:`load_team_from_dir`) on any validation
    failure — the running team is untouched in that case.
    """
    global _team, _team_last_used
    async with _lock:
        agents_dir = _resolve_agents_dir()

        # 1. Build candidate first — throws on validation failure, running
        #    team stays live.
        candidate = load_team_from_dir(agents_dir)
        if candidate is None:
            raise ValueError(
                f"No agents found in '{agents_dir}'. "
                "Create at least one .md file with 'role: lead' before reloading."
            )

        # 2. Snapshot the old team (for diff) and stop it.
        before_snapshot = _team_snapshot(_team) if _team is not None else None
        old_team = _team
        if old_team is not None:
            try:
                await old_team.stop()
            except Exception:
                logger.exception("team_manager_reload_stop_error")

        # 3. Start the new one.  ``app.api.deps.get_team`` will pick it up
        #    via :func:`current_team` on the next request.
        await candidate.start()
        _team = candidate
        _team_last_used = time.monotonic()

        diff = _compute_diff(before_snapshot, candidate)
        logger.info(
            "team_manager_reloaded lead={} added={} removed={} changed={}",
            diff.lead,
            diff.added,
            diff.removed,
            diff.changed,
        )
        return diff


# ── Live-config refresh ──────────────────────────────────────────────────────


def refresh_idle_agents(team: "AgentTeam") -> None:
    """Detect and apply config drift for all idle (non-working) agents.

    This is the same mechanism agents use at start-of-turn, hoisted into
    a service function so the ``GET /team/agents`` route can serve fresh
    frontmatter without knowing about ``TeamMemberBase`` internals.

    Working agents are skipped — refreshing them would race ``agent.run()``
    swapping ``self.agent`` mid-execution.

    Errors are swallowed and logged so a single bad agent config never
    breaks the listing endpoint.
    """
    for member in [team.lead, *team.members.values()]:
        if member.state == "working":
            continue
        try:
            member.refresh_if_dirty()
        except Exception as exc:
            logger.warning(
                "team_agents_refresh_failed name={} error={}", member.name, exc
            )


# ── Skill cache invalidation ─────────────────────────────────────────────────


def invalidate_skill_cache() -> None:
    """Clear the ``discover_skills`` lru_cache so the next tool call
    picks up edits to ``{SKILLS_DIR}/*/SKILL.md``.  No team reload needed.
    """
    from app.agent.tools.builtin.skill import _discover_skills_cached

    _discover_skills_cached.cache_clear()
    logger.info("team_manager_skill_cache_invalidated")
