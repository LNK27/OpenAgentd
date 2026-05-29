"""Drive a short session, force /compact, and print chat/summarization cache spans."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000/api"
SPANS = Path(".openagentd/dev/state/otel/spans")


def wait_done(base: str, sid: str, timeout: int) -> None:
    start = time.monotonic()
    with httpx.stream("GET", f"{base}/team/{sid}/stream", timeout=timeout + 5) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"timeout waiting for {sid}")
            if line.startswith("event:") and "done" in line:
                return


def send(base: str, message: str, sid: str | None, timeout: int) -> str:
    payload = {"message": message}
    if sid:
        payload["session_id"] = sid
    resp = httpx.post(f"{base}/team/chat", data=payload, timeout=30)
    resp.raise_for_status()
    sid = resp.json()["session_id"]
    wait_done(base, sid, timeout)
    return sid


def compact(base: str, sid: str, timeout: int) -> None:
    resp = httpx.post(
        f"{base}/team/commands",
        json={"command": "compact", "session_id": sid},
        timeout=30,
    )
    resp.raise_for_status()
    wait_done(base, sid, timeout)


def attrs_for_session(sid: str) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    time.sleep(2)
    for path in sorted(SPANS.glob("*.jsonl")):
        for line in path.open():
            if sid not in line:
                continue
            data = json.loads(line)
            name = data.get("name", "")
            if name.startswith("chat") or name.startswith("summarization"):
                rows.append((name, data.get("attributes", {})))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--turns", type=int, default=6)
    parser.add_argument("--wait", type=int, default=180)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    sid: str | None = None
    labels = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    for i in range(args.turns):
        label = labels[i % len(labels)]
        sid = send(base, f"cache smoke: reply with exactly {label}", sid, args.wait)
    assert sid is not None
    print(f"session: {sid}")
    compact(base, sid, args.wait)

    for name, attrs in attrs_for_session(sid):
        usage = {
            k: v
            for k, v in attrs.items()
            if "usage" in k or k.startswith("summarization") or k == "gen_ai.request.message_count"
        }
        print(name, usage)


if __name__ == "__main__":
    main()
