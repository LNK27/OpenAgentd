"""Smoke-test @-mention auto-attachment for team chat.

Sets up a temp coding workspace with fixtures, sends a chat message that
mentions a small text file, a large text file, an image, and a folder,
then reads the persisted user row directly from the DB and verifies:

  * the small text file was attached with the [File: ...] fence
  * the large text file was attached and head+tail truncated
  * the image mention did NOT produce an attachment (reference-only)
  * the folder mention attached that folder's AGENTS.md with its relative path
  * a mention written inside quotes / parens (e.g. ``"@note.txt"``)
    still resolves — guard for the regex boundary fix

The queue-path branch (mentions when the lead is busy) is covered by
unit tests; reproducing it here would require driving a real LLM turn
to keep the lead in ``working`` state, which is out of scope for this
fast smoke test.

Exits non-zero on any invariant failure.

Usage:
  uv run python -m manual.mention_attachments
  uv run python -m manual.mention_attachments --base http://localhost:8000/api
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx

from app.agent.multimodal import build_parts_from_metas

BASE = "http://localhost:8000/api"
BIG_HEAD = "HEAD_MARKER_ALPHA"
BIG_TAIL = "TAIL_MARKER_OMEGA"
MIDDLE_MARKER = "Middle truncated"


def make_fixtures(root: Path) -> None:
    (root / "note.txt").write_text("hello from note.txt\n", encoding="utf-8")
    (root / "quoted.txt").write_text("inside quotes\n", encoding="utf-8")

    # ~80KB → above 32K mention cap → must be truncated head+tail.
    filler = "x" * 80_000
    big = f"{BIG_HEAD}\n{filler}\n{BIG_TAIL}\n"
    (root / "big.txt").write_text(big, encoding="utf-8")

    # 1x1 PNG.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6300010000000500010d0a2db40000000049454e44"
        "ae426082"
    )
    (root / "photo.png").write_bytes(png)

    sub = root / "subdir"
    sub.mkdir()
    (sub / "inner.txt").write_text("inner\n", encoding="utf-8")
    (sub / "AGENTS.md").write_text("folder instructions\n", encoding="utf-8")


def post_chat(base: str, workspace: str, message: str) -> str:
    r = httpx.post(
        f"{base}/team/chat",
        data={"message": message, "mode": "coding", "workspace": workspace},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["session_id"]


def fetch_user_attachments(base: str, sid: str) -> list[dict]:
    """Read the first user row via the running API history endpoint."""
    r = httpx.get(f"{base}/team/{sid}/history", timeout=30)
    r.raise_for_status()
    messages = r.json()["lead"]["messages"]
    users = [m for m in messages if m.get("role") == "user"]
    if not users:
        return []
    extra = users[0].get("extra") or {}
    atts = extra.get("attachments") or []
    return list(atts)


def check(name: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{tag}] {name}{suffix}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description="Mention attachment smoke test")
    p.add_argument("--base", default=BASE)
    args = p.parse_args()
    base = args.base.rstrip("/")

    workspace = Path(tempfile.mkdtemp(prefix="mention-smoketest-"))
    print(f"workspace: {workspace}")
    try:
        make_fixtures(workspace)
        msg = (
            "Look at @note.txt and @big.txt and @photo.png and @subdir/ "
            'and also "@quoted.txt".'
        )
        sid = post_chat(base, str(workspace), msg)
        print(f"session : {sid}")

        # The user row is persisted before the LLM runs; a short wait is
        # enough. We don't care about the assistant reply for this test.
        time.sleep(2.0)
        atts = fetch_user_attachments(base, sid)
        by_name = {a.get("original_name") or a.get("filename"): a for a in atts}
        print(f"attached: {sorted(by_name)}")

        results = [
            check("note.txt attached", "note.txt" in by_name),
            check("big.txt attached", "big.txt" in by_name),
            check("quoted.txt attached (inside quotes)", "quoted.txt" in by_name),
            check("photo.png NOT attached", "photo.png" not in by_name),
            check("subdir/AGENTS.md attached", "subdir/AGENTS.md" in by_name),
            check("bare AGENTS.md label not used", "AGENTS.md" not in by_name),
        ]

        # Render the LLM-facing parts to verify fence + truncation, since
        # the fence is applied at build-time, not at persistence time.
        parts = build_parts_from_metas(msg, atts)
        rendered = {
            (a.get("original_name") or a.get("filename")): p.text
            for a, p in zip(atts, parts[: len(atts)])
            if hasattr(p, "text")
        }

        note_text = rendered.get("note.txt", "")
        results.append(
            check(
                "note.txt fenced",
                note_text.startswith("[File: note.txt]")
                and note_text.rstrip().endswith("[End file: note.txt]"),
            )
        )

        big_text = rendered.get("big.txt", "")
        results.append(
            check(
                "big.txt head preserved",
                BIG_HEAD in big_text,
            )
        )
        results.append(
            check(
                "big.txt tail preserved",
                BIG_TAIL in big_text,
            )
        )
        results.append(
            check(
                "big.txt truncated",
                MIDDLE_MARKER in big_text and len(big_text) < 60_000,
                f"len={len(big_text)}",
            )
        )

        ok = all(results)
        print(f"\n{'OK' if ok else 'FAIL'} ({sum(results)}/{len(results)})")
        return 0 if ok else 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
