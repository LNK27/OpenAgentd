"""Layer-by-layer latency benchmark for the /undo + /redo + sidebar flow.

Spins up a temporary git workspace, populates it with N files, then
calls each backend layer in-process and times it. Separates the cost
of:

  1. Snapshot ``track`` (called before saving a user message)
  2. Snapshot ``restore`` (called by /undo and /redo)
  3. File-list endpoint (``coding.files`` cache refresh)
  4. Git-diff endpoint, UNSCOPED (legacy whole-repo refresh)
  5. Git-diff endpoint, SCOPED to 1 file (Opt 2 fast path)
  6. Status endpoint (``coding.status`` cache refresh)

No live backend or real session required — the HTTP layer is bypassed
so this measures raw handler + git subprocess + filesystem cost. The
HTTP overhead is roughly 5–20 ms on top of these numbers for the live
request path.

Usage::

    uv run python scripts/bench_undo_redo_layers.py            # 50 files default
    uv run python scripts/bench_undo_redo_layers.py --files 500
    uv run python scripts/bench_undo_redo_layers.py --runs 10
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


async def _bench(files: int, runs: int) -> None:
    if shutil.which("git") is None:
        print("git binary not found — aborting", file=sys.stderr)
        return

    # Late imports so we can run from the repo root without installing.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.api.routes.team import files as files_route
    from app.services import snapshot_service

    workdir = Path(tempfile.mkdtemp(prefix="bench-layers-"))
    state = workdir / "state"
    state.mkdir()
    ws = workdir / "ws"
    ws.mkdir()

    # Initialise a real git repo so the diff endpoint exercises the
    # untracked scan + diff synthesis path.
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(ws), "config", "user.email", "bench@local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(ws), "config", "user.name", "bench"], check=True
    )

    # Seed N files committed at HEAD so the diff endpoint has tracked
    # content. Files are 200 bytes each — large enough to be realistic,
    # small enough that the diff text doesn't explode.
    print(f"populating {files} files...")
    for i in range(files):
        d = ws / f"d{i // 50}"
        d.mkdir(exist_ok=True)
        (d / f"f{i}.txt").write_text("x" * 200 + "\n")
    subprocess.run(["git", "-C", str(ws), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(ws), "commit", "-q", "-m", "init"], check=True
    )

    # Re-route the snapshot service at the tmp state dir.
    from app.core.config import settings

    settings.OPENAGENTD_STATE_DIR = str(state)

    session_id = "bench-session"

    # ── helpers ──────────────────────────────────────────────────────
    timings: dict[str, list[float]] = {
        "track_initial": [],
        "track_redo_anchor": [],
        "restore_undo": [],
        "restore_redo": [],
        "files_list": [],
        "diff_unscoped": [],
        "diff_scoped_1": [],
        "status": [],
    }

    async def _time(label: str, fn) -> None:
        t0 = time.perf_counter()
        await fn()
        dt = (time.perf_counter() - t0) * 1000
        timings[label].append(dt)

    # Initial snapshot of the clean workspace — this is what would
    # be stored on the user's first message.
    snap_initial = await snapshot_service.track(session_id, ws)
    assert snap_initial is not None

    # Simulate one user turn: agent edits 1 file.
    target_file = ws / "d0" / "f1.txt"

    for run in range(runs):
        # 1. Edit the file — simulates the agent's write tool.
        target_file.write_text(f"modified by run {run}\n" + "x" * 200 + "\n")
        # Also add 1 untracked file so the untracked-diff branch fires.
        untracked = ws / f"new_run_{run}.txt"
        untracked.write_text("fresh content\n")

        # 2. Track a new snapshot — what happens on the next user msg.
        await _time(
            "track_initial",
            lambda: snapshot_service.track(session_id, ws),
        )

        # 3. /undo: capture redo anchor (= current state), then restore initial.
        # Use ``skip_stage=True`` on restore — the just-completed track
        # left the index in sync with the worktree, so we don't need
        # to re-stage. Mirrors what chat_service.undo_session_messages
        # does in production.
        await _time(
            "track_redo_anchor",
            lambda: snapshot_service.track(session_id, ws),
        )
        await _time(
            "restore_undo",
            lambda: snapshot_service.restore(
                session_id, ws, snap_initial, skip_stage=True
            ),
        )

        # 4. Sidebar refresh — current code invalidates files+diff+status.
        async def call_files():
            await files_route.list_coding_workspace_files(str(ws))

        async def call_diff_unscoped():
            # Pass ``paths=None`` explicitly — calling the FastAPI handler
            # directly bypasses DI, so the ``Query(None)`` default is the
            # raw sentinel object, not None.
            await files_route.get_coding_workspace_git_diff(str(ws), paths=None)

        async def call_diff_scoped():
            await files_route.get_coding_workspace_git_diff(
                str(ws), paths=["d0/f1.txt"]
            )

        async def call_status():
            await files_route.get_coding_workspace_status(str(ws))

        # Run in the same order as the React bridge would, but
        # measured individually so we can attribute time.
        await _time("files_list", call_files)
        await _time("diff_unscoped", call_diff_unscoped)
        await _time("diff_scoped_1", call_diff_scoped)
        await _time("status", call_status)

        # 5. /redo: restore the redo anchor (puts us back at the edit).
        # Use the most recent track to keep state consistent.
        redo_snap = await snapshot_service.track(session_id, ws)
        if redo_snap:
            await _time(
                "restore_redo",
                lambda s=redo_snap: snapshot_service.restore(session_id, ws, s),
            )

    print()
    print(f"workspace: {files} files in {ws}")
    print(f"runs: {runs}\n")
    print(f"{'step':<22} {'min':>8} {'median':>8} {'mean':>8} {'max':>8}")
    print("-" * 60)
    for label, xs in timings.items():
        if not xs:
            continue
        print(
            f"{label:<22} {min(xs):>7.1f}ms {statistics.median(xs):>7.1f}ms "
            f"{statistics.mean(xs):>7.1f}ms {max(xs):>7.1f}ms"
        )

    # Print the cumulative end-to-end /undo cost as the user sees it,
    # using the current (broad invalidation) and proposed (scoped) paths.
    if timings["restore_undo"] and timings["diff_unscoped"]:
        broad = (
            statistics.median(timings["track_redo_anchor"])
            + statistics.median(timings["restore_undo"])
            + max(
                statistics.median(timings["files_list"]),
                statistics.median(timings["diff_unscoped"]),
                statistics.median(timings["status"]),
            )
        )
        scoped = (
            statistics.median(timings["track_redo_anchor"])
            + statistics.median(timings["restore_undo"])
            + max(
                statistics.median(timings["files_list"]),
                statistics.median(timings["diff_scoped_1"]),
                statistics.median(timings["status"]),
            )
        )
        print()
        print("end-to-end /undo (median, sidebar refresh in parallel):")
        print(f"  current  (broad invalidation):  {broad:6.1f}ms")
        print(f"  with Opt 3 (scoped diff splice): {scoped:6.1f}ms")
        print(f"  saved by Opt 3:                  {broad - scoped:6.1f}ms")

    # Cleanup
    shutil.rmtree(workdir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        type=int,
        default=50,
        help="number of files in the workspace (default: 50)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="iterations per layer (default: 5)",
    )
    args = parser.parse_args()
    asyncio.run(_bench(args.files, args.runs))


if __name__ == "__main__":
    main()
