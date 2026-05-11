"""AgentTeam — coordinates a team lead + members via mailbox activation.

Members are not built at startup; they exist as **blueprints** on the team
and are constructed on demand when the lead calls ``team_manage`` (see
:meth:`AgentTeam.spawn`).  Each spawn yields an instance handle of the form
``blueprint#N`` so the lead can run multiple parallel instances of the same
blueprint (e.g. ``executor#1`` and ``executor#2`` working in parallel) and
each instance has its own DB session / chat history.

Agents do **not** run persistent background loops.  Instead, ``register``
attaches an agent to the mailbox and installs an ``on_message`` callback
that activates the receiving agent on demand.

Streaming to the frontend uses the in-memory stream store: lifecycle events
(agent_status, done) are pushed to the same stream key as the LLM deltas,
so the frontend receives one unified event feed per session.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from loguru import logger
from sqlmodel import col, select

from app.agent.mode.team.mailbox import Message, TeamMailbox
from app.agent.mode.team.member import TeamLead, TeamMember, TeamMemberBase
from app.agent.mode.team.manage import make_team_configure_tool, make_team_manage_tool
from app.agent.mode.team.tools import make_team_message_tool
from app.agent.multimodal import build_parts_from_metas
from app.agent.schemas.chat import HumanMessage
from app.agent.schemas.events import DoneEvent
from app.agent.tools.registry import Tool
from app.core.db import DbFactory, resolve_db_factory
from app.models.chat import ChatSession
from app.services import memory_stream_store as stream_store
from app.services.stream_envelope import StreamEnvelope
from app.services.chat_service import heal_orphaned_tool_calls, save_message

if TYPE_CHECKING:
    from app.agent.providers.factory import ProviderFactory


# ---------------------------------------------------------------------------
# Blueprint registry
# ---------------------------------------------------------------------------


@dataclass
class MemberBlueprint:
    """A member ``.md`` file the lead can spawn instances from.

    Construction is deferred — the team holds blueprint metadata + the
    factories needed to build an Agent, and ``AgentTeam.spawn`` does the
    actual construction.
    """

    name: str  # blueprint name (matches the ``.md`` ``name:`` field)
    description: str
    source_path: Path
    # Monotonic per-blueprint counter — bumped each time an instance is
    # spawned in this process.  Spawning seeds it from the DB on first use
    # so it survives restarts (see AgentTeam._next_instance_id).
    next_instance_id: int = 1
    # ``True`` once spawn() has reconciled the counter against existing DB
    # sessions for the *current* lead session.  Reset when the lead session
    # changes so a fresh chat starts the counter at #1 again.
    counter_reconciled_for: str | None = field(default=None)


# ---------------------------------------------------------------------------
# Instance handle parsing
# ---------------------------------------------------------------------------


_INSTANCE_HANDLE_RE = re.compile(r"^(?P<blueprint>[^#]+)#(?P<n>\d+)$")


def parse_instance_handle(handle: str) -> tuple[str, int] | None:
    """Parse ``blueprint#N`` into ``(blueprint, N)``.  Return ``None`` on miss."""
    m = _INSTANCE_HANDLE_RE.match(handle)
    if not m:
        return None
    return m.group("blueprint"), int(m.group("n"))


def make_instance_handle(blueprint: str, n: int) -> str:
    """Format an instance handle from a blueprint name + counter."""
    return f"{blueprint}#{n}"


class AgentTeam:
    """Singleton team: one lead, N member blueprints, dynamic instance roster.

    Lifecycle::

        team = AgentTeam(lead=lead, blueprints={...}, ...)
        await team.start()   # registers lead with mailbox; members stay un-built
        ...
        await team.stop()    # cancels active tasks, deregisters all instances

    Spawn / dismiss::

        instance = await team.spawn("executor")          # → executor#1
        instance = await team.spawn("executor")          # → executor#2
        await team.dismiss("executor#1")                 # frees the agent
        instance = await team.spawn("executor", instance_id=1)  # restore #1

    Handling a user message::

        session_id = await team.handle_user_message(content="...", session_id="...")
        # client subscribes to GET /team/stream/{session_id}
    """

    def __init__(
        self,
        lead: TeamLead,
        blueprints: dict[str, "MemberBlueprint"] | None = None,
        *,
        provider_factory: "ProviderFactory | None" = None,
        extra_tools: dict[str, Tool] | None = None,
        db_factory: DbFactory | None = None,
        # Back-compat: callers (especially older tests) can still pass a
        # pre-built members map.  These instances are registered as if they
        # were spawned by name; their handles stay verbatim (no ``#1``
        # suffix is added) so existing tests keep passing.
        members: dict[str, "TeamMember"] | None = None,
    ) -> None:
        self.lead = lead
        self.blueprints: dict[str, MemberBlueprint] = blueprints or {}
        self.members: dict[str, TeamMember] = dict(members or {})

        self._provider_factory = provider_factory
        self._extra_tools = extra_tools
        self._db_factory = db_factory

        self.mailbox = TeamMailbox(on_message=self._on_message)

        # Guard: only emit done after at least one user turn has started
        self._has_active_turn: bool = False

        # Index agents by name for fast lookup in on_message.  Kept in sync
        # by spawn() / dismiss().
        self._members_by_name: dict[str, TeamMemberBase] = {lead.name: lead}
        for name, m in self.members.items():
            self._members_by_name[name] = m

        # Serialise spawn / dismiss against each other.  The mailbox + DB
        # work is short, but two concurrent roster-management calls from the
        # same lead turn could otherwise race the counter.
        self._roster_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the lead with the mailbox.

        Members are NOT registered here — they exist as blueprints and are
        registered when ``team_manage`` materialises an instance.  Pre-existing
        members in ``self.members`` (e.g. supplied directly by tests via the
        ``members=`` constructor kwarg) are also registered for back-compat.
        """
        self.lead.register(self)
        for member in self.members.values():
            member.register(self)
        logger.info(
            "agent_team_started lead={} blueprints={} eager_members={}",
            self.lead.name,
            sorted(self.blueprints.keys()),
            list(self.members.keys()),
        )

    async def stop(self) -> None:
        """Gracefully stop all agents: cancel active tasks and deregister."""
        for member in list(self.members.values()):
            await member.stop()
        await self.lead.stop()
        logger.info("agent_team_stopped")

    # ------------------------------------------------------------------
    # On-message activation callback
    # ------------------------------------------------------------------

    async def _on_message(self, agent_name: str, message: Message) -> None:
        """Called by the mailbox after every send.  Activates the target agent."""
        member = self._members_by_name.get(agent_name)
        if member is None:
            logger.warning("team_on_message_unknown_agent agent={}", agent_name)
            return
        member._maybe_activate()

    # ------------------------------------------------------------------
    # Stream event helpers
    # ------------------------------------------------------------------

    async def _emit(
        self,
        agent: str,
        event: str,
        status: Literal["idle", "working", "offline", "error"] | None = None,
        extra: dict | None = None,
    ) -> None:
        """Push a lifecycle event to the stream store for the current session."""
        from app.agent.schemas.events import AgentStatusEvent

        session_id = self.lead.session_id
        if event == "agent_status" and status is not None:
            envelope = StreamEnvelope.from_event(
                AgentStatusEvent(
                    agent=agent,
                    status=status,
                    metadata=extra or {},
                )
            )
        else:
            envelope = StreamEnvelope.from_parts(
                event,
                {"type": event, "agent": agent, "event": event, **(extra or {})},
            )

        try:
            await stream_store.push_event(session_id, envelope)
        except Exception as exc:
            logger.warning("team_emit_failed event={} error={}", event, exc)

    async def _try_emit_done(self) -> None:
        """Emit 'done' when lead + all live members are idle.

        Called from every member's _run_activation finally block.
        Guard: only fires after at least one user turn has started.
        """
        if not self._has_active_turn:
            return
        lead_done = self.lead.state in ("idle", "error")
        all_members_done = all(
            m.state in ("idle", "error") for m in self.members.values()
        )
        if lead_done and all_members_done:
            self._has_active_turn = False  # reset for next turn
            session_id = self.lead.session_id

            try:
                await stream_store.push_event(
                    session_id,
                    StreamEnvelope.from_event(DoneEvent()),
                )
                await stream_store.mark_done(session_id)
            except Exception as exc:
                logger.warning("team_emit_done_failed error={}", exc)
            logger.info("team_turn_done session_id={}", session_id)

    # ------------------------------------------------------------------
    # User message entry point
    # ------------------------------------------------------------------

    async def handle_user_message(
        self,
        content: str,
        session_id: str,
        interrupt: bool = False,
        attachment_metas: list[dict] | None = None,
    ) -> str:
        """Deliver a user message to the team lead. Returns the session_id.

        ``session_id`` controls which conversation the lead continues.
        Passing a new UUID starts a fresh lead conversation.

        If interrupt=True, all working agents are cancelled immediately and
        all non-completed tasks are reset so the lead can re-plan.

        The caller should subscribe to GET /team/stream/{session_id} to
        receive the SSE event stream.
        """
        # Update the lead's active session
        is_new_session = self.lead.session_id != session_id
        if is_new_session:
            self.lead.session_id = session_id
            await self.lead._ensure_db_session(
                title=content[:100] if content else None,
            )

            # Reset blueprint counters so a fresh chat starts at #1 for each
            # blueprint.  (Reconciliation against existing DB rows is done
            # lazily on the first spawn for the new lead session.)
            for bp in self.blueprints.values():
                bp.counter_reconciled_for = None

            # Restore previously-spawned-and-not-dismissed instances by
            # rehydrating their session ids from DB.  Any instance that was
            # alive (registered) when we entered this branch keeps its
            # mailbox registration; we only update its DB session pointer
            # so its view of history matches whatever child rows exist
            # for the current lead session.
            #
            # This preserves the existing "restart restores members"
            # behaviour for instances that had been spawned earlier in the
            # process — but only for those that actually had child rows
            # under THIS lead session.  Anything else is dropped from the
            # roster (the lead can re-spawn at will).
            await self._restore_or_drop_members_for_lead(session_id)

        if interrupt:
            cancelled = [m for m in self.all_members if m.state == "working"]
            for member in cancelled:
                member._cancel_event.set()

            logger.info(
                "team_interrupted cancelled={}",
                [m.name for m in cancelled],
            )

        # Persist user message and parent member sessions
        try:
            db_factory = resolve_db_factory(self.lead.db_factory)
            lead_uuid = UUID(session_id)
            async with db_factory() as db:
                # Build multimodal HumanMessage if attachments present
                if attachment_metas:
                    parts = build_parts_from_metas(content, attachment_metas)
                    user_msg = HumanMessage(content=content, parts=parts)
                    msg_extra: dict | None = {"attachments": attachment_metas}
                else:
                    user_msg = HumanMessage(content=content)
                    msg_extra = None

                # Heal any tool_calls left orphaned by a previous crash /
                # restart *before* persisting the new user message so the
                # next turn's LLM input is well-formed.  See
                # ``heal_orphaned_tool_calls`` for the full rationale.
                await heal_orphaned_tool_calls(db, lead_uuid)

                await save_message(db, lead_uuid, user_msg, extra=msg_extra)

                for member in self.members.values():
                    try:
                        member_uuid = UUID(member.session_id)
                        member_row = await db.get(ChatSession, member_uuid)
                        if (
                            member_row is not None
                            and member_row.parent_session_id != lead_uuid
                        ):
                            member_row.parent_session_id = lead_uuid
                            db.add(member_row)
                    except Exception as inner_exc:
                        logger.warning(
                            "team_parent_member_session_failed member={} error={}",
                            member.name,
                            inner_exc,
                        )

                await db.commit()
        except Exception as exc:
            logger.warning("team_save_user_message_failed error={}", exc)

        # Initialise a fresh state blob for this turn synchronously before
        # delivering the message to the lead. This guarantees the state key
        # exists by the time the client's GET /team/stream/{sid} arrives.
        try:
            await stream_store.init_turn(session_id)
        except Exception as exc:
            logger.warning("team_init_turn_failed error={}", exc)

        # Mark that a turn is now active
        self._has_active_turn = True

        # Deliver user message to lead inbox (on_message callback activates lead)
        msg = Message(
            from_agent="user",
            to_agent=self.lead.name,
            content=f"[user]: {content}",
        )
        await self.mailbox.send(to=self.lead.name, message=msg)

        return session_id

    async def _restore_or_drop_members_for_lead(self, lead_session_id: str) -> None:
        """Realign live spawned instances to child sessions of *lead_session_id*.

        For each currently-live ``blueprint#N`` instance:
          - If a child ``ChatSession`` row with matching ``agent_name``
            exists under this lead, point the member at it (history is
            preserved).
          - Otherwise, dismiss it: the lead can re-spawn it explicitly,
            and we don't want to silently mint a fresh DB session for a
            member that may have been spawned for a different conversation.

        Plain-name eager members (those constructed directly via the
        ``members=`` constructor kwarg, used by tests) are left untouched —
        they own their own session id and are not part of the dynamic
        blueprint roster.
        """
        if not self.members:
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            lead_uuid = UUID(lead_session_id)
        except ValueError:
            return  # caller passed a non-UUID; nothing we can do

        try:
            async with db_factory() as db:
                for handle, member in list(self.members.items()):
                    is_spawned = parse_instance_handle(handle) is not None
                    result = await db.exec(
                        select(ChatSession)
                        .where(col(ChatSession.parent_session_id) == lead_uuid)
                        .where(col(ChatSession.agent_name) == handle)
                        .order_by(col(ChatSession.created_at).desc())
                        .limit(1)
                    )
                    existing = result.first()
                    if existing is not None:
                        # Realign to the existing child row regardless of
                        # whether the member was blueprint-spawned or eager:
                        # this preserves the legacy "restart restores
                        # members" behaviour.
                        member.session_id = str(existing.id)
                    elif is_spawned:
                        # No child session for this lead AND it's a
                        # blueprint-spawned instance → drop it.  The lead
                        # can re-spawn explicitly.  Eager / test-injected
                        # members are left in place with their existing
                        # session id.
                        await self._dismiss_live_member(handle)
        except Exception as exc:
            logger.warning("team_restore_members_failed error={}", exc)

    # ------------------------------------------------------------------
    # Spawn / dismiss
    # ------------------------------------------------------------------

    async def spawn(
        self,
        blueprint: str,
        *,
        instance_id: int | None = None,
    ) -> TeamMember:
        """Materialise a member instance from a blueprint and register it.

        Args:
            blueprint: Blueprint name (matches a ``.md`` file's ``name:``).
            instance_id: If given, spawn (or restore) the instance with that
                ``#N``.  If a DB ``ChatSession`` already exists for this
                ``(lead_session, handle)`` it is restored (history preserved).
                Otherwise a fresh session is created.  When omitted, the
                next free ``#N`` is auto-assigned (handles auto-suffixing
                when the same blueprint is spawned multiple times).

        Raises:
            KeyError: blueprint not found.
            ValueError: instance with that handle is already live.
        """
        async with self._roster_lock:
            return await self._spawn_locked(blueprint, instance_id=instance_id)

    async def _spawn_locked(
        self,
        blueprint: str,
        *,
        instance_id: int | None,
    ) -> TeamMember:
        bp = self.blueprints.get(blueprint)
        if bp is None:
            idle = sorted(self.blueprints.keys())
            raise KeyError(f"Unknown blueprint '{blueprint}'. Available: {idle}.")

        # Reconcile counter for this lead session if not yet done.  This
        # ensures auto-assigned ``#N`` values are restart-safe and don't
        # collide with old child sessions.
        await self._reconcile_counter(bp)

        if instance_id is None:
            instance_id = bp.next_instance_id
            # Skip over any handle that's already live for this blueprint.
            while make_instance_handle(blueprint, instance_id) in self.members:
                instance_id += 1
            bp.next_instance_id = instance_id + 1
        else:
            if instance_id < 1:
                raise ValueError(f"instance_id must be >= 1 (got {instance_id}).")
            # Keep the auto-counter ahead of any explicit id so subsequent
            # auto-spawns don't immediately collide.
            if instance_id >= bp.next_instance_id:
                bp.next_instance_id = instance_id + 1

        handle = make_instance_handle(blueprint, instance_id)
        if handle in self.members:
            raise ValueError(f"Instance '{handle}' is already live.")

        # Build the agent from the blueprint's .md file.
        from app.agent.loader import rebuild_agent_from_disk

        agent = rebuild_agent_from_disk(
            bp.source_path,
            provider_factory=self._provider_factory,
            extra_tools=self._extra_tools,
        )
        # The blueprint name on disk is e.g. ``executor``; the runtime name
        # (mailbox key, DB ``agent_name``) is the instance handle.
        agent.name = handle

        member = TeamMember(agent, db_factory=self._db_factory)

        # Resolve session id: restore if an existing row matches this
        # (lead, handle) — including the legacy "bare blueprint name"
        # adoption for instance #1 (see ``_resolve_session_for_handle``).
        session_id = await self._resolve_session_for_handle(blueprint, handle)
        if session_id is not None:
            member.session_id = session_id
        # Ensure the row exists (idempotent on restore) and parent it
        # under the current lead session so the team-history endpoint
        # and the counter reconciler can find it.
        await member._ensure_db_session()
        await self._parent_member_session(member)

        # Register with mailbox.  The team is currently started iff the
        # lead has a registered inbox; in that case we activate immediately
        # so any queued messages are picked up.
        member.register(self)
        self.members[handle] = member
        self._members_by_name[handle] = member
        await self._emit(
            agent=handle,
            event="agent_status",
            status="idle",
            extra={"blueprint": blueprint},
        )

        logger.info(
            "team_member_spawned blueprint={} handle={} session_id={}",
            blueprint,
            handle,
            member.session_id,
        )
        return member

    async def _parent_member_session(self, member: TeamMember) -> None:
        """Set ``parent_session_id`` on *member*'s DB row to the lead's session.

        The team's lead session is the canonical parent for all member
        sessions.  ``handle_user_message`` already does this for *every*
        member at the start of a turn, but spawn happens mid-turn so we
        need to set it eagerly so counter reconciliation, history APIs,
        and dismiss-then-respawn all see the row under the right lead.
        """
        try:
            lead_uuid = UUID(self.lead.session_id)
            member_uuid = UUID(member.session_id)
        except (ValueError, AttributeError):
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with db_factory() as db:
                row = await db.get(ChatSession, member_uuid)
                if row is None:
                    return
                if row.parent_session_id != lead_uuid:
                    row.parent_session_id = lead_uuid
                    db.add(row)
                    await db.commit()
        except Exception as exc:
            logger.warning(
                "team_parent_member_session_failed handle={} error={}",
                member.name,
                exc,
            )

    async def dismiss(self, handle: str) -> bool:
        """Stop and deregister an instance by handle.  Returns ``True`` if found.

        DB session row is preserved so the instance can later be respawned
        with its history intact via ``spawn(blueprint, instance_id=N)``.
        """
        async with self._roster_lock:
            return await self._dismiss_live_member(handle)

    async def _dismiss_live_member(self, handle: str) -> bool:
        member = self.members.pop(handle, None)
        if member is None:
            return False
        self._members_by_name.pop(handle, None)
        try:
            await member.stop()
        except Exception as exc:
            logger.warning("team_dismiss_stop_failed handle={} error={}", handle, exc)
        logger.info("team_member_dismissed handle={}", handle)
        await self._emit(agent=handle, event="agent_status", status="offline")
        return True

    # ------------------------------------------------------------------
    # Counter reconciliation + session resolution
    # ------------------------------------------------------------------

    async def _reconcile_counter(self, bp: "MemberBlueprint") -> None:
        """Seed ``bp.next_instance_id`` from the DB for the current lead session.

        Counter scope is **per-lead-session**: each fresh chat starts a
        blueprint at ``#1``.  The DB is the source of truth — the counter
        becomes ``max(existing #N for this lead) + 1`` so it survives a
        process restart in the middle of a live conversation.

        The first time a session sees a particular blueprint with no
        ``#N`` rows but an existing legacy bare-name row, the bare name is
        adopted as ``#1`` (see ``_resolve_session_for_handle``).
        """
        lead_session_id = self.lead.session_id
        if bp.counter_reconciled_for == lead_session_id:
            return

        try:
            lead_uuid = UUID(lead_session_id)
        except (ValueError, AttributeError):
            bp.counter_reconciled_for = lead_session_id
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        max_n = 0
        try:
            async with db_factory() as db:
                # Look only at rows that already use the new ``blueprint#N``
                # naming.  Legacy bare-name rows are NOT counted here —
                # they are adopted as ``#1`` on first spawn (see
                # ``_resolve_session_for_handle``), and counting them as
                # ``#1`` ahead of time would cause the first spawn to
                # auto-pick ``#2`` and skip the adoption opportunity.
                result = await db.exec(
                    select(ChatSession.agent_name).where(
                        col(ChatSession.parent_session_id) == lead_uuid
                    )
                )
                names = result.all()
                for name in names:
                    if not name:
                        continue
                    parsed = parse_instance_handle(name)
                    if parsed and parsed[0] == bp.name:
                        max_n = max(max_n, parsed[1])
        except Exception as exc:
            logger.warning(
                "team_counter_reconcile_failed blueprint={} error={}",
                bp.name,
                exc,
            )

        bp.next_instance_id = max_n + 1
        bp.counter_reconciled_for = lead_session_id

    async def _resolve_session_for_handle(
        self,
        blueprint: str,
        handle: str,
    ) -> str | None:
        """Return an existing DB session id for this (lead, handle), if any.

        Adoption rule: the very first time blueprint ``X`` is spawned for a
        given lead session as ``X#1`` AND no row already exists for the
        ``X#1`` agent_name, but a legacy bare-name row ``X`` exists under
        the same lead — adopt that row as ``X#1`` (rewrite ``agent_name``
        in place).  This makes the move from the old single-instance model
        lossless: the lead's existing ``executor`` history shows up under
        ``executor#1`` without manual migration.
        """
        try:
            lead_uuid = UUID(self.lead.session_id)
        except (ValueError, AttributeError):
            return None

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with db_factory() as db:
                # 1) Exact handle match (e.g. respawning ``executor#3``).
                result = await db.exec(
                    select(ChatSession)
                    .where(col(ChatSession.parent_session_id) == lead_uuid)
                    .where(col(ChatSession.agent_name) == handle)
                    .order_by(col(ChatSession.created_at).desc())
                    .limit(1)
                )
                row = result.first()
                if row is not None:
                    return str(row.id)

                # 2) Legacy adoption — only for the ``#1`` instance.
                parsed = parse_instance_handle(handle)
                if parsed is not None and parsed == (blueprint, 1):
                    legacy_q = await db.exec(
                        select(ChatSession)
                        .where(col(ChatSession.parent_session_id) == lead_uuid)
                        .where(col(ChatSession.agent_name) == blueprint)
                        .order_by(col(ChatSession.created_at).desc())
                        .limit(1)
                    )
                    legacy = legacy_q.first()
                    if legacy is not None:
                        legacy.agent_name = handle
                        db.add(legacy)
                        await db.commit()
                        logger.info(
                            "team_member_legacy_adopted blueprint={} handle={} "
                            "session_id={}",
                            blueprint,
                            handle,
                            legacy.id,
                        )
                        return str(legacy.id)
        except Exception as exc:
            logger.warning(
                "team_resolve_session_failed handle={} error={}", handle, exc
            )
        return None

    # ------------------------------------------------------------------
    # Recipient resolution (for team_message)
    # ------------------------------------------------------------------

    def resolve_recipient(self, name: str) -> str | None:
        """Resolve a recipient name to a live mailbox key.

        - Exact handle match (``executor#2``) → returned as-is if live.
        - Bare blueprint name (``executor``) → routes to the unique live
          instance if exactly one exists.  Returns ``None`` to signal
          ambiguity (caller should produce a tailored error) when zero or
          multiple live instances exist.
        - Lead name → returned as-is.

        Returns the live name to address, or ``None`` if there is no
        unambiguous match.
        """
        if name == self.lead.name:
            return name
        if name in self.members:
            return name
        # Bare blueprint name: collect all live ``blueprint#N`` instances.
        candidates = [
            handle
            for handle in self.members
            if (parsed := parse_instance_handle(handle)) is not None
            and parsed[0] == name
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def live_instances_for_blueprint(self, blueprint: str) -> list[str]:
        """Return live instance handles for *blueprint* in spawn order."""
        matches: list[tuple[int, str]] = []
        for handle in self.members:
            parsed = parse_instance_handle(handle)
            if parsed is not None and parsed[0] == blueprint:
                matches.append((parsed[1], handle))
        matches.sort(key=lambda x: x[0])
        return [handle for _, handle in matches]

    # ------------------------------------------------------------------
    # Tool injection
    # ------------------------------------------------------------------

    def get_injected_tools(self, agent_name: str) -> list[Tool]:
        """Return runtime tools to inject into agent.run() for the given agent.

        Everyone gets ``team_message`` and ``todo_manage`` so members can claim
        assigned tasks. The lead additionally gets ``team_manage`` (roster
        spawn/dismiss) and ``team_configure`` (capability management).
        """
        from app.agent.tools.builtin.todo import make_todo_manage_tool

        role = "lead" if agent_name == self.lead.name else "member"
        tools: list[Tool] = [
            make_team_message_tool(
                self.mailbox, agent_name=agent_name, role=role, team=self
            ),
            make_todo_manage_tool(role),
        ]

        if agent_name == self.lead.name:
            tools.append(make_team_manage_tool(self))
            tools.append(make_team_configure_tool(self))

        return tools

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def all_members(self) -> list[TeamMemberBase]:
        """Lead + all live members (instances)."""
        return [self.lead, *self.members.values()]

    def status(self) -> dict:
        """Return current state of all live agents + blueprint roster."""
        return {
            "lead": {
                "name": self.lead.name,
                "state": self.lead.state,
                "model": self.lead.agent.llm_provider.model,
            },
            "members": [
                {
                    "name": m.name,
                    "state": m.state,
                    "model": m.agent.llm_provider.model,
                }
                for m in self.members.values()
            ],
            "blueprints": [
                {
                    "name": bp.name,
                    "description": bp.description,
                    "live_instances": self.live_instances_for_blueprint(bp.name),
                }
                for bp in self.blueprints.values()
            ],
        }
