"""End-to-end /undo HTTP latency benchmark with per-stage breakdown.

This script answers the question "where do the milliseconds go on a real
``POST /api/team/commands?command=undo`` request?" The other bench scripts
measure either the snapshot service in isolation or the route handler at
the function level. This one drives the actual FastAPI app via
``TestClient`` so every layer is exercised:

  1. HTTP request parse + Pydantic validation
  2. ``_require_team`` lookup
  3. Per-session command lock acquisition
  4. DB session open
  5. ``ChatSession`` row fetch
  6. ``undo_session_messages``:
       - ``_revert_boundary`` lookup (2 row fetches)
       - user-message SELECT (full session scan)
       - ``snapshot_service.track`` for the redo anchor
       - ``snapshot_service.restore`` to the target snapshot
       - ``ChatSession.revert`` write + ``db.flush()``
  7. ``db.commit()`` (SQLite WAL fsync)
  8. ``db.refresh(target)`` (extra SELECT on the target row)
  9. JSON response serialization
 10. HTTP response write

We populate a temp workspace with N files, create a chat session with M
user turns, snapshot each turn, then call /undo and report per-stage
latency.

Usage::

    uv run python scripts/bench_undo_http.py --files 100 --turns 5
    uv run python scripts/bench_undo_http.py --files 5000 --turns 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _patch_env(workspace: Path, state: Path):
    """Point openagentd at temporary directories before importing the app."""
    db_path = state / "db.sqlite"
    env = {
        "OPENAGENTD_STATE_DIR": str(state),
        "OPENAGENTD_DB_PATH": str(db_path),
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _populate_workspace(ws: Path, count: int) -> None:
    """Fill ``ws`` with ``count`` small text files spread across 10 dirs."""
    print(f"populating {count} files in {ws}...")
    for i in range(count):
        d = ws / f"d{i % 10}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.txt").write_text(f"file {i}\nline2\nline3\n")


async def _seed(workspace: Path, turns: int) -> str:
    """Create a chat session with ``turns`` user messages, each snapshotting
    the workspace. Returns the session id. Mirrors what the team agent does
    on every user-message save in production.

    Caller must have already run migrations *outside* the event loop —
    Alembic's env.py calls ``asyncio.run`` internally so it can't run from
    inside an existing loop.
    """
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession, SessionMessage
    from app.services import snapshot_service

    async with async_session_factory() as db:
        chat = ChatSession(title="bench", agent_name="lead")
        db.add(chat)
        await db.flush()
        sid = str(chat.id)

        for i in range(turns):
            # Mutate a single file each turn so restore has work to do but
            # ``track`` doesn't blow up on a huge delta.
            target = workspace / f"d{i % 10}" / f"f{i}.txt"
            target.write_text(f"turn {i}\n")
            snap = await snapshot_service.track(sid, workspace)
            db.add(
                SessionMessage(
                    session_id=chat.id,
                    role="user",
                    content=f"user turn {i}",
                    extra={"snapshot": snap},
                )
            )
            db.add(
                SessionMessage(
                    session_id=chat.id,
                    role="assistant",
                    content=f"assistant reply {i}",
                )
            )
            await db.flush()

        await db.commit()

    return sid


def _install_timing_probes() -> dict[str, list[float]]:
    """Wrap key chat_service / snapshot_service functions with timing probes.

    Returns a dict mapping ``label -> [ms]`` populated as the handler runs.
    Each /undo request appends one entry per probe. Use to attribute the
    end-to-end HTTP latency to specific backend stages without printing
    inside the handler.
    """
    from app.services import chat_service as cs
    from app.services import snapshot_service as ss

    timings: dict[str, list[float]] = {
        "track_call": [],
        "track_list_candidates": [],
        "track_stage": [],
        "track_write_tree": [],
        "restore_call": [],
        "undo_session_messages": [],
    }

    orig_track = ss.track
    orig_restore = ss.restore
    orig_undo = cs.undo_session_messages
    orig_list = ss._list_candidate_paths
    orig_stage = ss._stage
    orig_git = ss._git

    async def timed_list(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await orig_list(*a, **kw)
        finally:
            timings["track_list_candidates"].append(
                (time.perf_counter() - t0) * 1000
            )

    async def timed_stage(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await orig_stage(*a, **kw)
        finally:
            timings["track_stage"].append((time.perf_counter() - t0) * 1000)

    async def timed_git(*a, **kw):
        # We only care about write-tree here; everything else is
        # already accounted for by list/stage wrappers.
        if "write-tree" in a:
            t0 = time.perf_counter()
            try:
                return await orig_git(*a, **kw)
            finally:
                timings["track_write_tree"].append(
                    (time.perf_counter() - t0) * 1000
                )
        return await orig_git(*a, **kw)

    async def timed_track(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await orig_track(*a, **kw)
        finally:
            timings["track_call"].append((time.perf_counter() - t0) * 1000)

    async def timed_restore(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await orig_restore(*a, **kw)
        finally:
            timings["restore_call"].append((time.perf_counter() - t0) * 1000)

    async def timed_undo(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await orig_undo(*a, **kw)
        finally:
            timings["undo_session_messages"].append(
                (time.perf_counter() - t0) * 1000
            )

    ss.track = timed_track  # type: ignore[assignment]
    ss.restore = timed_restore  # type: ignore[assignment]
    ss._list_candidate_paths = timed_list  # type: ignore[assignment]
    ss._stage = timed_stage  # type: ignore[assignment]
    ss._git = timed_git  # type: ignore[assignment]
    cs.undo_session_messages = timed_undo  # type: ignore[assignment]
    # Re-patch the bound import inside team.py
    from app.agent.mode.team import team as team_mod
    team_mod.undo_session_messages = timed_undo  # type: ignore[assignment]
    return timings


def main(files: int, turns: int, runs: int) -> None:
    with tempfile.TemporaryDirectory(prefix="bench-undo-http-") as tmp:
        root = Path(tmp)
        ws = root / "ws"
        ws.mkdir()
        state = root / "state"
        state.mkdir()

        with _patch_env(ws, state):
            _populate_workspace(ws, files)

            # Importing after env patch so the app picks the temp DB path.
            from fastapi.testclient import TestClient

            from app.agent.agent_loop import Agent
            from app.agent.mode.team.member import TeamLead
            from app.agent.mode.team.team import AgentTeam
            from app.api.app import create_app
            from app.core import db as _db
            from app.core.db import run_migrations
            from app.services.team_manager import set_team
            from tests.api.routes.test_team_db import MockProvider

            # Alembic spins up its own event loop; must run outside ours.
            run_migrations()
            sid = asyncio.run(_seed(ws, turns))
            print(f"seeded session: {sid} ({turns} turns)\n")

            async def _start_team():
                lead = TeamLead(
                    Agent(name="lead", llm_provider=MockProvider(), system_prompt="Lead"),
                    db_factory=_db.async_session_factory,
                )
                t = AgentTeam(lead=lead, members={})
                await t.start()
                return t

            team = asyncio.run(_start_team())
            app = create_app()
            set_team(team)

            # Patch session workspace so the snapshot service lands in ``ws``.
            # Without this it tries to derive a workspace from the session row
            # which doesn't match our temp setup.
            import app.services.chat_service as cs

            cs.session_workspace_dir = lambda _sid, _w, _ws=ws: _ws  # type: ignore[assignment]

            with TestClient(app) as client:
                # Warm-up so JIT / connection pool / etc. don't skew the
                # first timing.
                client.post(
                    "/api/team/commands",
                    json={"command": "undo", "session_id": sid},
                )
                client.post(
                    "/api/team/commands",
                    json={"command": "redo", "session_id": sid},
                )

                # Attach probes AFTER warm-up so they only see the
                # measured runs. Warm-up call sites no longer match the
                # patched references but that's fine — they ran already.
                probe_timings = _install_timing_probes()

                undos = []
                for _ in range(runs):
                    t0 = time.perf_counter()
                    resp = client.post(
                        "/api/team/commands",
                        json={"command": "undo", "session_id": sid},
                    )
                    dt = (time.perf_counter() - t0) * 1000
                    if resp.status_code != 202:
                        raise RuntimeError(
                            f"undo failed: {resp.status_code} {resp.text}"
                        )
                    undos.append(dt)
                    # Put it back so the next /undo has something to do.
                    client.post(
                        "/api/team/commands",
                        json={"command": "redo", "session_id": sid},
                    )

    print(f"\nworkspace: {files} files, session: {turns} turns, runs: {runs}\n")
    print(f"{'metric':<22} {'min':>9} {'median':>9} {'mean':>9} {'max':>9}")
    print("-" * 70)
    # ``probe_timings`` only captured during the measured runs (after
    # warm-up + probe install). Slice to the /undo half so we report
    # what happened during the measured HTTP calls.
    def _undo_only(samples: list[float]) -> list[float]:
        # Probes wrap BOTH /undo and the trailing /redo (since they're
        # the same backend symbols). The first call per iteration is
        # always /undo, so even indices are /undo and odd indices are
        # /redo. Slice accordingly.
        return samples[0 : 2 * runs : 2] if len(samples) >= 2 * runs else samples

    def _row(label: str, samples: list[float]) -> None:
        if not samples:
            print(f"{label:<22} {'n/a':>9}")
            return
        print(
            f"{label:<22} "
            f"{min(samples):>8.1f}ms "
            f"{statistics.median(samples):>8.1f}ms "
            f"{statistics.mean(samples):>8.1f}ms "
            f"{max(samples):>8.1f}ms"
        )

    _row("/undo (full HTTP)", undos)
    _row("undo_session_messages", _undo_only(probe_timings["undo_session_messages"]))
    _row("snapshot.track", _undo_only(probe_timings["track_call"]))
    _row(" └─ list_candidates", _undo_only(probe_timings["track_list_candidates"]))
    _row(" └─ stage (git add)", _undo_only(probe_timings["track_stage"]))
    _row(" └─ write-tree", _undo_only(probe_timings["track_write_tree"]))
    _row("snapshot.restore", _undo_only(probe_timings["restore_call"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--files", type=int, default=100)
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    try:
        main(args.files, args.turns, args.runs)
    except KeyboardInterrupt:
        sys.exit(130)
