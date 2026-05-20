"""End-to-end /undo + /redo HTTP latency benchmark.

Drives the actual ``POST /api/team/commands`` endpoint against a running
backend and reports wall-clock latency per command. Use this when the
frontend feels slow — separates network/DB/handler cost from snapshot
work measured by ``bench_snapshot.py``.

Usage::

    # 1. Start the backend separately (so it's warm):
    make dev   # or: uv run uvicorn app.api.app:app --port 8000

    # 2. In another terminal, run with an existing session id that has
    #    at least one user message you can undo / redo against:
    uv run python scripts/bench_undo_redo.py \
        --session 019e44c2-... \
        --runs 5

The script alternates undo → redo so the session state stays the same
across runs. Reports per-call latency in ms with min/median/mean/max.
"""

from __future__ import annotations

import argparse
import statistics
import time

import httpx


def _call(client: httpx.Client, base: str, command: str, sid: str) -> float:
    t0 = time.perf_counter()
    resp = client.post(
        f"{base}/api/team/commands",
        json={"command": command, "session_id": sid},
        timeout=30.0,
    )
    elapsed = (time.perf_counter() - t0) * 1000
    if resp.status_code >= 400:
        raise RuntimeError(
            f"{command} → {resp.status_code}: {resp.text.strip()}"
        )
    return elapsed


def main(base: str, sid: str, runs: int) -> None:
    print(f"target: {base}  session: {sid}  runs: {runs}\n")
    undos: list[float] = []
    redos: list[float] = []
    with httpx.Client() as client:
        # Warm-up call — first request often pays import + connection cost.
        try:
            _call(client, base, "undo", sid)
            _call(client, base, "redo", sid)
        except RuntimeError as exc:
            raise SystemExit(f"warm-up failed: {exc}")

        for i in range(runs):
            t_undo = _call(client, base, "undo", sid)
            t_redo = _call(client, base, "redo", sid)
            undos.append(t_undo)
            redos.append(t_redo)
            print(f"run {i + 1}/{runs}: undo={t_undo:6.1f}ms  redo={t_redo:6.1f}ms")

    def _row(label: str, xs: list[float]) -> None:
        print(
            f"{label:<6} min={min(xs):6.1f}ms  "
            f"median={statistics.median(xs):6.1f}ms  "
            f"mean={statistics.mean(xs):6.1f}ms  "
            f"max={max(xs):6.1f}ms"
        )

    print()
    _row("undo", undos)
    _row("redo", redos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base", default="http://localhost:8000", help="backend base URL"
    )
    parser.add_argument(
        "--session", required=True, help="ChatSession UUID to bounce"
    )
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    main(args.base, args.session, args.runs)
