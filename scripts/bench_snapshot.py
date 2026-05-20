"""Micro-benchmark for the workspace snapshot service.

Spins up a temporary workspace with N files, runs the full
``track`` → mutate → ``track`` → ``restore`` cycle, and reports
per-step latency in milliseconds. Use this when tuning the git
subprocess path in :mod:`app.services.snapshot_service` (e.g.
parallelism, ``--no-optional-locks``, stage skipping).

Usage::

    uv run python scripts/bench_snapshot.py
    uv run python scripts/bench_snapshot.py --files 200 --runs 5
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from pathlib import Path

from app.core.config import settings
from app.services import snapshot_service


async def _bench_once(num_files: int) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as t:
        state = Path(t) / "state"
        state.mkdir()
        settings.OPENAGENTD_STATE_DIR = str(state)
        ws = Path(t) / "ws"
        ws.mkdir()

        # Realistic workspace shape: small text + a few subdirs.
        for i in range(num_files):
            sub = ws / f"pkg{i % 5}"
            sub.mkdir(exist_ok=True)
            (sub / f"f{i}.txt").write_text("x" * 200)

        timings: dict[str, float] = {}

        t0 = time.perf_counter()
        baseline = await snapshot_service.track("bench", ws)
        timings["track_initial"] = (time.perf_counter() - t0) * 1000
        assert baseline is not None

        # Mutate a few files + add one new.
        (ws / "pkg0" / "f0.txt").write_text("changed by agent")
        (ws / "pkg1" / "new.txt").write_text("new artifact")

        t0 = time.perf_counter()
        live = await snapshot_service.track("bench", ws)
        timings["track_redo_anchor"] = (time.perf_counter() - t0) * 1000
        assert live is not None

        t0 = time.perf_counter()
        await snapshot_service.restore("bench", ws, baseline)
        timings["restore_undo"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        await snapshot_service.restore("bench", ws, live)
        timings["restore_redo"] = (time.perf_counter() - t0) * 1000

        # End-to-end "what /undo does on the server side": track redo
        # anchor + restore target snapshot.
        # Reset & rebuild a small mutation so this run is realistic.
        (ws / "pkg2" / "tmp.txt").write_text("tmp")
        t0 = time.perf_counter()
        anchor = await snapshot_service.track("bench", ws)
        await snapshot_service.restore("bench", ws, baseline)
        timings["undo_cycle"] = (time.perf_counter() - t0) * 1000
        assert anchor is not None

        return timings


async def main(num_files: int, runs: int) -> None:
    print(f"workspace: {num_files} files, {runs} runs\n")
    headers = (
        "track_initial",
        "track_redo_anchor",
        "restore_undo",
        "restore_redo",
        "undo_cycle",
    )
    results: dict[str, list[float]] = {h: [] for h in headers}

    for i in range(runs):
        timings = await _bench_once(num_files)
        for h in headers:
            results[h].append(timings[h])
        line = "  ".join(f"{h}={timings[h]:6.1f}ms" for h in headers)
        print(f"run {i + 1}/{runs}: {line}")

    print()
    print(f"{'step':<22} {'min':>8} {'median':>8} {'mean':>8} {'max':>8}")
    print("-" * 60)
    for h in headers:
        xs = results[h]
        print(
            f"{h:<22} {min(xs):>7.1f}ms {statistics.median(xs):>7.1f}ms "
            f"{statistics.mean(xs):>7.1f}ms {max(xs):>7.1f}ms"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=50)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.files, args.runs))
