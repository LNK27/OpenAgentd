"""Dream service — consolidate wiki from unprocessed sessions and notes.

Dream reads unprocessed chat sessions and note files, runs the dream agent
over each one, and writes to wiki/topics/, wiki/USER.md, wiki/INDEX.md.

The dream agent is loaded from .openagentd/config/dream.md.  If that file is
missing, has no ``model:`` field, or ``enabled: false``, synthesis is skipped
and items are still marked as processed (infrastructure-only mode).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, DreamLog, DreamNotesLog, SessionMessage
from app.services.wiki import NOTES_DIR, TOPICS_DIR, wiki_root

if TYPE_CHECKING:
    import contextvars

    from app.agent.agent_loop import Agent
    from app.agent.sandbox import SandboxConfig

_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)

# ── Dream config schema ───────────────────────────────────────────────────────

# Tools always injected into the dream agent regardless of dream.md listing.
# ``edit`` and ``rm`` are required by the system prompt — without them, the
# "surgical update" and (rare) "delete on user request" rules cannot be honoured.
_REQUIRED_TOOLS: list[str] = ["read", "write", "edit", "rm", "ls", "wiki_search"]

# Hard caps to keep dream resilient. These exist to bound failure modes — they
# are not knobs users typically need to tune.
DEFAULT_LLM_TIMEOUT_SECONDS = 300  # 5 min — covers most reasonable transcripts
DEFAULT_MAX_PROMPT_CHARS = 60_000  # ~15k tokens — fits inside any modern context
PER_MESSAGE_CAP_CHARS = 4_000

# Serialise dream runs so manual /api/dream/run cannot race the scheduler fire
# and crash on the dream_log.session_id UNIQUE constraint.
_run_lock = asyncio.Lock()


class DreamAgentConfig(BaseModel):
    """Parsed configuration from dream.md.

    Extends the agent frontmatter schema with dream-specific fields
    (``enabled``, ``schedule``, ``batch_size``, ``timeout_seconds``).
    Dream.md is NOT a regular agent file — it has its own loader so these
    fields are first-class, not silently ignored extras.
    """

    # ── Agent identity (mirrors AgentConfig subset) ──
    name: str = "dream"
    model: str | None = None
    description: str | None = None
    temperature: float | None = None
    thinking_level: str | None = None
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = ""

    # ── Dream-specific ────────────────────────────────
    enabled: bool = False
    schedule: str = "0 2 * * *"
    batch_size: int = 1
    """Number of sessions/notes to process per run_dream() call.

    Defaults to 1 — each scheduler fire (or manual /dream/run trigger)
    processes exactly one item with a fresh agent instance.  Increase for
    bulk catch-up runs, but keep small enough that the LLM context stays
    focused on one conversation at a time.
    """

    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    """Per-item LLM timeout. Hard cap so a stuck provider can't wedge dream
    forever (and block scheduler reload / shutdown).
    """

    @model_validator(mode="after")
    def _inject_required_tools(self) -> "DreamAgentConfig":
        for tool in _REQUIRED_TOOLS:
            if tool not in self.tools:
                self.tools.append(tool)
        return self

    @model_validator(mode="after")
    def _validate_model(self) -> "DreamAgentConfig":
        if self.model and ":" not in self.model:
            raise ValueError(
                f"Dream model '{self.model}' must be 'provider:model' "
                "(e.g. 'googlegenai:gemini-2.0-flash')."
            )
        return self


def parse_dream_md(path: Path) -> DreamAgentConfig:
    """Parse dream.md into a :class:`DreamAgentConfig`.

    dream.md uses the same ``---\\nyaml\\n---\\nbody`` format as agent files,
    with the body becoming the system prompt and dream-specific frontmatter
    keys (``enabled``, ``schedule``, ``batch_size``, ``timeout_seconds``).

    Raises :exc:`ValueError` when the file is missing a frontmatter block or
    the YAML is invalid.
    """
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(
            f"dream.md at '{path}' is missing YAML frontmatter "
            "(expected '---\\n<yaml>\\n---\\n<system prompt>')."
        )
    try:
        raw: dict = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"dream.md YAML parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("dream.md frontmatter must be a YAML mapping.")

    # Warn if the user accidentally specified ``system_prompt`` in the
    # frontmatter — dream.md's contract is "body becomes system prompt",
    # so a frontmatter override would be silently ignored otherwise.
    if "system_prompt" in raw:
        logger.warning(
            "dream_md_frontmatter_system_prompt_ignored path={} "
            "(use the markdown body as the system prompt instead)",
            path,
        )

    # Normalise CRLF → LF so a Windows-edited dream.md doesn't smuggle ``\r``
    # bytes into the LLM system prompt (some providers reject them, others
    # silently strip and de-sync the rendered token count).
    body = m.group(2).replace("\r\n", "\n").replace("\r", "\n").strip()
    raw["system_prompt"] = body or "You are the dream agent."

    # name defaults to "dream" if not set in the file
    raw.setdefault("name", "dream")

    cfg = DreamAgentConfig.model_validate(raw)

    # Surface a config-time warning if dream is enabled but has no model.
    # Synthesis will silently be skipped (infra-only mode), but users
    # almost certainly forgot to set ``model:`` rather than asking for
    # this on purpose.
    if cfg.enabled and not cfg.model:
        logger.warning(
            "dream_md_enabled_without_model path={} "
            "(synthesis will be skipped; set 'model: provider:name' to enable)",
            path,
        )

    return cfg


# ── Helpers ───────────────────────────────────────────────────────────────────


# Default sentinel agent_name for dream's own sessions.  Overridable via
# ``dream.md`` (``name:`` field) and passed to ``get_unprocessed_sessions``
# so dream cannot feed itself even if the agent is renamed.
DREAM_AGENT_NAME = "dream"


async def get_unprocessed_sessions(
    db: AsyncSession, *, dream_agent_name: str = DREAM_AGENT_NAME
) -> list[ChatSession]:
    """Return sessions not yet in dream_log, excluding empty sessions and
    sessions belonging to the dream agent itself.

    This is a **pure read** — empty-session log rows are written by
    :func:`run_dream` so transaction boundaries stay correct.

    ``dream_agent_name`` defaults to ``"dream"`` but is overridden by
    :func:`_run_dream_locked` with the active ``dream_cfg.name`` so renaming
    the dream agent via ``dream.md`` does not create a feedback loop.
    """
    processed_ids_result = await db.exec(select(DreamLog.session_id))
    processed_ids = set(processed_ids_result.all())

    all_sessions_result = await db.exec(select(ChatSession))
    all_sessions = all_sessions_result.all()

    return [
        s
        for s in all_sessions
        if s.id not in processed_ids and s.agent_name != dream_agent_name
    ]


async def _session_has_messages(db: AsyncSession, session: ChatSession) -> bool:
    """Return True if the session has at least one non-system, non-excluded
    message.  Used by :func:`run_dream` to split empties from real work.
    """
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session.id)
        .where(~col(SessionMessage.exclude_from_context))
        .where(col(SessionMessage.role) != "system")
        .limit(1)
    )
    return bool((await db.exec(stmt)).first())


async def get_unprocessed_notes(db: AsyncSession) -> list[str]:
    """Return note filenames not yet in dream_notes_log."""
    root = wiki_root()
    notes_dir = root / NOTES_DIR
    if not notes_dir.is_dir():
        return []

    processed_result = await db.exec(select(DreamNotesLog.filename))
    processed = set(processed_result.all())

    all_notes = [
        entry.name
        for entry in sorted(notes_dir.iterdir())
        if entry.is_file() and entry.suffix == ".md"
    ]
    return [n for n in all_notes if n not in processed]


async def mark_session_processed(
    db: AsyncSession,
    session_id: uuid.UUID,
    agent_name: str,
    topics_written: list[str],
) -> None:
    """Insert row into dream_log and commit immediately.

    Per-item commit so a later crash cannot roll back earlier successes
    (or leave wiki files on disk without a corresponding ``dream_log`` row).

    Silently swallows :class:`IntegrityError` when the session is already
    logged — the ``dream_log.session_id`` UNIQUE constraint can be tripped
    by an out-of-process race (e.g. ``manual.dream run --direct`` running
    while the server fires a scheduled run).  ``_run_lock`` only guards
    the in-process case, so we must still tolerate the cross-process one.
    """
    log = DreamLog(
        session_id=session_id,
        processed_at=datetime.now(timezone.utc),
        agent_name=agent_name,
        topics_written=json.dumps(list(dict.fromkeys(topics_written)))
        if topics_written
        else None,
    )
    db.add(log)
    try:
        await db.commit()
    except IntegrityError:
        # Cross-process race only — dedupe and move on.
        await db.rollback()
        logger.info(
            "dream_log_already_marked session_id={} agent={}",
            session_id,
            agent_name,
        )
    except Exception:
        # Disk full, lock timeout, schema drift — re-raise after rolling
        # back so the caller can surface the failure.  Do NOT silence;
        # silent swallowing would re-process the same session forever.
        await db.rollback()
        logger.exception(
            "dream_log_commit_failed session_id={} agent={}",
            session_id,
            agent_name,
        )
        raise


async def mark_note_processed(db: AsyncSession, filename: str) -> None:
    """Insert row into dream_notes_log and commit immediately.

    Silently swallows :class:`IntegrityError` for the same cross-process
    race reason as :func:`mark_session_processed`.  Any other commit error
    is re-raised after rollback so it doesn't get masked.
    """
    log = DreamNotesLog(
        filename=filename,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(log)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.info("dream_notes_log_already_marked filename={}", filename)
    except Exception:
        await db.rollback()
        logger.exception("dream_notes_log_commit_failed filename={}", filename)
        raise


async def _mark_item_processed(
    db: AsyncSession,
    kind: str,
    item: ChatSession | str,
    *,
    topics_written: list[str] | None = None,
) -> None:
    """Dispatch to the appropriate ``mark_*_processed`` for one work item.

    Removes a duplicate block in the infra-only / loader-failure branches
    of :func:`_run_dream_locked`.
    """
    if kind == "session":
        # Explicit type check (not ``assert``) so ``python -O`` doesn't
        # silently turn a programming error into a misleading
        # ``AttributeError`` deep in ``mark_session_processed``.
        if not isinstance(item, ChatSession):
            raise TypeError(
                f"_mark_item_processed kind='session' expects ChatSession, "
                f"got {type(item).__name__}"
            )
        await mark_session_processed(
            db,
            session_id=item.id,
            agent_name=item.agent_name or "unknown",
            topics_written=topics_written or [],
        )
    else:
        if not isinstance(item, str):
            raise TypeError(
                f"_mark_item_processed kind='note' expects str, "
                f"got {type(item).__name__}"
            )
        await mark_note_processed(db, item)


# ── Dream agent loader ────────────────────────────────────────────────────────


def _load_dream_agent(
    cfg: "DreamAgentConfig",
) -> "tuple[Agent, contextvars.Token[SandboxConfig]] | None":
    """Load the dream agent from a parsed :class:`DreamAgentConfig`.

    Returns a tuple of ``(agent, sandbox_token)`` so the caller can restore
    the previous sandbox via :func:`contextvars.Token.reset` once the run
    completes.  Returns ``None`` when no model is configured.

    The caller is responsible for resetting the sandbox — failure to do so
    leaks the wiki workspace into any subsequent activity on the same
    asyncio task.

    Construction order matters: the ``AgentConfig`` is validated FIRST
    (it can raise on bad model strings, missing tools, etc.), so the
    sandbox is only mutated when we know the build will proceed.  This
    keeps the contract simple: ``set_sandbox`` is paired exactly with the
    returned token; no token leaks on early validation failures.
    """
    from app.agent.loader import AgentConfig, _build_agent, _default_tool_registry
    from app.agent.providers.factory import build_provider
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox

    if not cfg.model:
        logger.debug("dream_agent_skip no model configured")
        return None

    # Project DreamAgentConfig → AgentConfig (the agent builder's contract).
    # role is always "member" for the dream agent — it never leads a team.
    # Build the AgentConfig BEFORE touching the sandbox so a validation
    # failure can't leak a half-set sandbox context.
    try:
        agent_cfg = AgentConfig(
            name=cfg.name,
            role="member",
            description=cfg.description,
            model=cfg.model,
            temperature=cfg.temperature,
            thinking_level=cfg.thinking_level,
            tools=list(cfg.tools),
            system_prompt=cfg.system_prompt,
        )
    except Exception as exc:
        logger.warning("dream_agent_config_build_failed error={}", exc)
        return None

    # Set the sandbox workspace to wiki_root() so the dream agent's filesystem
    # tools (ls, read, write, edit, rm) resolve relative paths against the
    # wiki directory.  Keep the token so the caller can restore.
    token = set_sandbox(SandboxConfig(workspace=str(wiki_root())))

    try:
        config_path = _dream_config_path()
        agent = _build_agent(
            agent_cfg,
            _default_tool_registry(),
            build_provider,
            source_path=config_path,
        )
        logger.info("dream_agent_loaded model={} tools={}", cfg.model, cfg.tools)
        return agent, token
    except Exception as exc:
        logger.warning("dream_agent_build_failed error={}", exc)
        _sandbox_ctx.reset(token)
        return None


def _dream_config_path() -> Path:
    from app.core.config import settings

    return Path(settings.OPENAGENTD_CONFIG_DIR) / "dream.md"


# ── Session transcript formatter ──────────────────────────────────────────────


async def _fetch_session_transcript(
    db: AsyncSession,
    session: ChatSession,
    *,
    max_total_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> str:
    """Return a readable transcript of the session for the dream agent.

    Bounded by ``max_total_chars``: per-message truncation comes first
    (long single messages get clipped to ``PER_MESSAGE_CAP_CHARS``), then
    if the assembled transcript still exceeds the cap, the **oldest middle**
    messages are dropped — first and last messages are kept verbatim so
    the LLM still sees how the conversation opened and concluded.
    """
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session.id)
        .where(~col(SessionMessage.exclude_from_context))
        .order_by(col(SessionMessage.created_at).asc())
    )
    rows = (await db.exec(stmt)).all()

    if not rows:
        return "(empty session)"

    # Header is intentionally minimal — the dream LLM should consolidate
    # *content*, not opaque IDs.  Embedding ``session.id`` here would leak
    # raw UUIDs into the generated topic files.  Agent name + a date stamp
    # are enough provenance for the model to reason about "when did this
    # come from" without polluting the wiki.
    created_date = (
        session.created_at.strftime("%Y-%m-%d") if session.created_at else "unknown"
    )
    header = [
        f"Agent: {session.agent_name or 'unknown'}",
        f"Date: {created_date}",
        "",
    ]
    header_text = "\n".join(header)

    def _render(msg: SessionMessage) -> str:
        content = msg.content or ""
        if len(content) > PER_MESSAGE_CAP_CHARS:
            content = content[:PER_MESSAGE_CAP_CHARS] + "\n[... truncated ...]"
        return f"### {msg.role.upper()}\n{content}\n"

    rendered = [_render(m) for m in rows]
    budget = max_total_chars - len(header_text)

    # Drop oldest middle messages until we fit. Always keep first + last.
    # ``total_len`` is tracked incrementally so the loop stays O(n) — a
    # naive ``sum(len(r) for r in rendered)`` on every iteration would be
    # O(n²) for very long conversations.
    #
    # ``elision_present`` is the loop invariant: a single marker at
    # index 1 once we've dropped anything.  Inserting it once and then
    # popping subsequent middles around it avoids a "remove-then-add"
    # infinite loop a naive implementation produces when only the
    # first + last + elision remain.
    elision = "### [... middle messages elided to fit context window ...]\n"
    total_len = sum(len(r) for r in rendered)
    elision_present = False
    while total_len > budget:
        # The drop target is whichever non-anchor slot is right after the
        # first message (index 1, or 2 if the elision marker holds slot 1).
        drop_idx = 2 if elision_present else 1
        if drop_idx >= len(rendered) - 1:
            # Only first + (elision) + last remain — no more middles to drop.
            break
        removed = rendered.pop(drop_idx)
        total_len -= len(removed)
        if not elision_present:
            rendered.insert(1, elision)
            total_len += len(elision)
            elision_present = True

    return header_text + "\n".join(rendered)


# ── Topics diff helper ────────────────────────────────────────────────────────


def _topics_snapshot() -> dict[str, int]:
    """Return ``{filename: mtime_ns}`` for every topic file.

    Used to detect both new files **and** modifications to existing files
    — a plain set-difference would only catch creates and silently log
    in-place edits as "no topics written".

    Uses ``st_mtime_ns`` (integer nanoseconds) instead of ``st_mtime``
    (float seconds) so two writes within the same second on filesystems
    with coarse mtime granularity (HFS+, FAT32) still surface as changes.
    """
    topics_dir = wiki_root() / TOPICS_DIR
    if not topics_dir.is_dir():
        return {}
    snap: dict[str, int] = {}
    for f in topics_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            try:
                snap[f.name] = f.stat().st_mtime_ns
            except OSError:
                continue
    return snap


def _diff_topics(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Return slugs of topic files that were created, modified, OR deleted.

    Tracking deletes matters for audit fidelity: when the dream LLM uses
    ``rm`` to drop a stale topic, the action should show up in
    ``dream_log.topics_written`` instead of being recorded as "(none)".
    Slugs are deduped via a set (defensive — a single mtime snapshot won't
    surface the same slug twice, but cheap insurance against caller bugs).
    """
    changed: set[str] = set()
    for name, mtime in after.items():
        if name not in before or mtime > before[name]:
            changed.add(Path(name).stem)
    for name in before.keys() - after.keys():
        changed.add(Path(name).stem)
    return sorted(changed)


# ── LLM synthesis ─────────────────────────────────────────────────────────────


class _SynthesisFailed(RuntimeError):
    """Raised when the LLM call fails — distinguishes failure from
    'ran successfully but produced no topics' so the caller can skip
    ``mark_*_processed`` and retry on the next run.
    """


async def _synthesise_session(
    agent: "Agent",
    db: AsyncSession,
    session: ChatSession,
    *,
    timeout_seconds: int,
) -> list[str]:
    """Run the dream agent over one session.

    Returns the list of changed topic slugs on success.  Raises
    :class:`_SynthesisFailed` when the LLM call errors or times out —
    the caller uses this to skip ``mark_session_processed`` so the
    session is retried on the next dream run.
    """
    from app.agent.schemas.agent import RunConfig
    from app.agent.schemas.chat import HumanMessage

    transcript = await _fetch_session_transcript(db, session)
    if transcript == "(empty session)":
        logger.debug("dream_session_empty session_id={}", session.id)
        return []

    prompt = (
        "Process the following conversation session and update the wiki accordingly.\n\n"
        f"{transcript}"
    )

    before = _topics_snapshot()
    try:
        # Pass an empty RunConfig — NOT the target session's id.  Dream
        # runs are not part of the user's conversation history and nothing
        # in dream relies on RunContext.session_id, so leaving it None is
        # correct.  Using ``str(uuid.uuid4())`` (UUIDv4) here would also
        # produce a garbage ``session_created_at`` because RunConfig's
        # validator decodes a UUIDv7 timestamp from the top 48 bits.
        await asyncio.wait_for(
            agent.run(
                [HumanMessage(content=prompt)],
                config=RunConfig(),
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "dream_session_llm_timeout session_id={} timeout_seconds={}",
            session.id,
            timeout_seconds,
        )
        raise _SynthesisFailed("LLM timeout") from exc
    except Exception as exc:
        logger.warning(
            "dream_session_llm_failed session_id={} error={}", session.id, exc
        )
        raise _SynthesisFailed(str(exc)) from exc

    after = _topics_snapshot()
    return _diff_topics(before, after)


async def _synthesise_note(
    agent: "Agent",
    filename: str,
    *,
    timeout_seconds: int,
) -> list[str]:
    """Run the dream agent over one note file.

    Returns changed topic slugs on success; raises :class:`_SynthesisFailed`
    when the LLM call errors or times out.
    """
    from app.agent.schemas.agent import RunConfig
    from app.agent.schemas.chat import HumanMessage

    note_path = wiki_root() / NOTES_DIR / filename
    try:
        content = note_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("dream_note_read_failed filename={} error={}", filename, exc)
        raise _SynthesisFailed(f"note read failed: {exc}") from exc

    if not content.strip():
        return []

    prompt = (
        "Process the following note and update the wiki accordingly.\n\n"
        f"Note file: {filename}\n\n"
        f"{content}"
    )

    before = _topics_snapshot()
    try:
        await asyncio.wait_for(
            agent.run(
                [HumanMessage(content=prompt)],
                config=RunConfig(),
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "dream_note_llm_timeout filename={} timeout_seconds={}",
            filename,
            timeout_seconds,
        )
        raise _SynthesisFailed("LLM timeout") from exc
    except Exception as exc:
        logger.warning("dream_note_llm_failed filename={} error={}", filename, exc)
        raise _SynthesisFailed(str(exc)) from exc

    after = _topics_snapshot()
    return _diff_topics(before, after)


# ── Main entry point ──────────────────────────────────────────────────────────


async def run_dream(db: AsyncSession) -> dict:
    """Process up to ``batch_size`` unprocessed items (interleaved sessions
    and notes) under a global lock so concurrent invocations cannot race
    on the ``dream_log.session_id`` UNIQUE constraint.

    Each item gets its own fresh agent instance so no conversation history
    bleeds between items.  Sessions and notes are **interleaved** (one of
    each per round) so a backlog of sessions cannot starve notes.

    Returns::

        {
            "sessions_processed": N,
            "notes_processed": M,
            "remaining": R,
            "failed": F,
        }
    """
    async with _run_lock:
        return await _run_dream_locked(db)


async def _run_dream_locked(db: AsyncSession) -> dict:
    """Inner implementation — assumes ``_run_lock`` is held."""
    # Parse dream.md once and pass the config down — avoids re-reading the
    # file mid-run if the user edits it (bug #14).  Wrap in ``to_thread``
    # because YAML parsing + ``Path.read_text`` are synchronous and would
    # otherwise block the event loop, stalling other FastAPI requests (A2).
    dream_cfg: DreamAgentConfig | None = None
    config_path = _dream_config_path()
    if config_path.exists():
        try:
            dream_cfg = await asyncio.to_thread(parse_dream_md, config_path)
        except ValueError as exc:
            logger.warning("dream_run_config_parse_failed error={}", exc)

    batch_size = max(1, dream_cfg.batch_size) if dream_cfg else 1
    timeout_seconds = (
        dream_cfg.timeout_seconds if dream_cfg else DEFAULT_LLM_TIMEOUT_SECONDS
    )

    dream_agent_name = dream_cfg.name if dream_cfg else DREAM_AGENT_NAME
    unprocessed_sessions = await get_unprocessed_sessions(
        db, dream_agent_name=dream_agent_name
    )
    unprocessed_notes = await get_unprocessed_notes(db)

    # Empty-session marking moved here from get_unprocessed_sessions so the
    # write side-effect is no longer hidden inside a read function (bug #3).
    #
    # Cap empties drained per run to avoid commit-storms when a long-lived
    # deployment accumulates thousands of test/abandoned empty sessions.  The
    # cap is generous (100x ``batch_size`` so a healthy backlog still drains
    # quickly) but bounded so one fire cannot block on thousands of commits.
    empty_session_drain_cap = max(100, batch_size * 100)
    real_sessions: list[ChatSession] = []
    empty_count = 0
    empty_mark_failures = 0
    for session in unprocessed_sessions:
        if await _session_has_messages(db, session):
            real_sessions.append(session)
            continue
        if empty_count >= empty_session_drain_cap:
            # Stop marking — leftover empties will be picked up by the next
            # run.  Don't break the loop entirely: real sessions found after
            # this point still need to be enqueued for synthesis.
            continue
        try:
            await _mark_item_processed(db, "session", session)
            empty_count += 1
        except Exception:
            # A transient commit failure (disk full, lock timeout) must
            # not abort the whole run — log it, advance, and let the next
            # run retry.  ``mark_session_processed`` already logged the
            # exception with full traceback via ``logger.exception``.
            empty_mark_failures += 1
            logger.warning(
                "dream_empty_session_mark_failed session_id={} retry_next_run=true",
                session.id,
            )
    if empty_count or empty_mark_failures:
        logger.info(
            "dream_skipped_empty_sessions count={} failures={} drain_cap={}",
            empty_count,
            empty_mark_failures,
            empty_session_drain_cap,
        )

    total_remaining = len(real_sessions) + len(unprocessed_notes)
    if total_remaining == 0:
        logger.info("dream_run_nothing_to_process")
        return {
            "sessions_processed": 0,
            "notes_processed": 0,
            "remaining": 0,
            "failed": 0,
        }

    logger.info(
        "dream_run_start sessions={} notes={} batch_size={} timeout_s={}",
        len(real_sessions),
        len(unprocessed_notes),
        batch_size,
        timeout_seconds,
    )

    sessions_processed = 0
    notes_processed = 0
    failed = 0

    # Interleave: one session, one note, one session, ... up to batch_size.
    work: list[tuple[str, ChatSession | str]] = []
    s_iter = iter(real_sessions)
    n_iter = iter(unprocessed_notes)
    while len(work) < batch_size:
        added = False
        try:
            work.append(("session", next(s_iter)))
            added = True
        except StopIteration:
            pass
        if len(work) >= batch_size:
            break
        try:
            work.append(("note", next(n_iter)))
            added = True
        except StopIteration:
            pass
        if not added:
            break

    # Sandbox restoration is handled per-item via ``_sandbox_ctx.reset(token)``
    # in the inner ``finally`` block below — each ``_load_dream_agent`` call
    # set the wiki workspace and returned a token, and resetting it pops the
    # wiki sandbox back off the contextvar stack.  No outer scope needed:
    # if any item is skipped (e.g. ``_load_dream_agent`` returns ``None``), no
    # token was set and no reset is needed for that item.
    from app.agent.sandbox import _sandbox_ctx

    for kind, item in work:
        item_label = (
            f"session_id={item.id}"
            if isinstance(item, ChatSession)
            else f"filename={item}"
        )
        item_start = datetime.now(timezone.utc)
        logger.info("dream_item_start kind={} {}", kind, item_label)

        # Infrastructure-only mode (no dream.md or loader failure): mark the
        # item so it doesn't pile up forever, but skip synthesis.
        if dream_cfg is None:
            try:
                await _mark_item_processed(db, kind, item)
            except Exception:
                failed += 1
                logger.warning(
                    "dream_infra_mark_failed kind={} {} retry_next_run=true",
                    kind,
                    item_label,
                )
                continue
            if kind == "session":
                sessions_processed += 1
            else:
                notes_processed += 1
            continue

        loaded = _load_dream_agent(dream_cfg)
        if loaded is None:
            try:
                await _mark_item_processed(db, kind, item)
            except Exception:
                failed += 1
                logger.warning(
                    "dream_loader_skip_mark_failed kind={} {} retry_next_run=true",
                    kind,
                    item_label,
                )
                continue
            if kind == "session":
                sessions_processed += 1
            else:
                notes_processed += 1
            continue

        agent, sandbox_token = loaded
        try:
            if kind == "session":
                if not isinstance(item, ChatSession):
                    raise TypeError(  # pragma: no cover - defensive
                        f"work-tuple type drift: kind=session item={type(item).__name__}"
                    )
                try:
                    topics_written = await _synthesise_session(
                        agent, db, item, timeout_seconds=timeout_seconds
                    )
                except _SynthesisFailed:
                    failed += 1
                    logger.warning(
                        "dream_session_failed session_id={} retry_next_run=true",
                        item.id,
                    )
                    continue
                try:
                    await _mark_item_processed(
                        db, kind, item, topics_written=topics_written
                    )
                except Exception:
                    # Synthesis succeeded but commit failed — leave the
                    # session unprocessed so the next run retries.  The
                    # wiki side-effect is already persisted.
                    failed += 1
                    logger.warning(
                        "dream_session_mark_failed session_id={} retry_next_run=true",
                        item.id,
                    )
                    continue
                sessions_processed += 1
                duration = (datetime.now(timezone.utc) - item_start).total_seconds()
                logger.info(
                    "dream_session_processed session_id={} agent={} topics={} duration_s={:.1f}",
                    item.id,
                    item.agent_name,
                    topics_written,
                    duration,
                )
            else:
                if not isinstance(item, str):
                    raise TypeError(  # pragma: no cover - defensive
                        f"work-tuple type drift: kind=note item={type(item).__name__}"
                    )
                try:
                    topics_written = await _synthesise_note(
                        agent, item, timeout_seconds=timeout_seconds
                    )
                except _SynthesisFailed:
                    failed += 1
                    logger.warning(
                        "dream_note_failed filename={} retry_next_run=true",
                        item,
                    )
                    continue
                try:
                    await _mark_item_processed(db, kind, item)
                except Exception:
                    failed += 1
                    logger.warning(
                        "dream_note_mark_failed filename={} retry_next_run=true",
                        item,
                    )
                    continue
                notes_processed += 1
                duration = (datetime.now(timezone.utc) - item_start).total_seconds()
                logger.info(
                    "dream_note_processed filename={} topics={} duration_s={:.1f}",
                    item,
                    topics_written,
                    duration,
                )
        finally:
            # Always release the sandbox token so the wiki workspace
            # doesn't leak into the caller's context.
            _sandbox_ctx.reset(sandbox_token)

    remaining = total_remaining - sessions_processed - notes_processed
    result = {
        "sessions_processed": sessions_processed,
        "notes_processed": notes_processed,
        "remaining": remaining,
        "failed": failed,
    }
    logger.info("dream_run_complete result={}", result)
    return result
