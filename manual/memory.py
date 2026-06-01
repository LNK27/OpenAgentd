"""Inspect and exercise memory v2 helpers.

Manual commands for the Karpathy-style memory/wiki plan. Commands use the
Memory v2 service directly where available and intentionally do not change
backend runtime behaviour.

Usage:
  uv run python -m manual.memory tree
  uv run python -m manual.memory search "what does Hoang prefer?"
  uv run python -m manual.memory maintain --limit 1
  uv run python -m manual.memory index
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.db import async_session_factory
from app.services import memory


def cmd_tree() -> None:
    tree = memory.list_memory_tree()
    print(f"\nMemory root: {memory.memory_root()}\n")
    sections = [
        ("system", tree.system),
        ("wiki", tree.wiki),
        ("imports", tree.imports),
        ("notes", tree.notes),
    ]
    for name, files in sections:
        print(f"  {name}/  ({len(files)} files)")
        for f in files:
            desc = f" — {f.description}" if f.description else ""
            print(f"    {f.path}{desc}")
        if not files:
            print("    (empty)")
        print()


async def cmd_search(query: str, *, limit: int, raw: bool) -> None:
    limit = max(1, limit)
    if raw:
        async with async_session_factory() as db:
            hits = await memory.memory_search(query, db=db, limit=limit)
    else:
        hits = memory.search_memory_files(query, limit=limit)
    if not hits:
        print("No matches.")
        return
    for i, hit in enumerate(hits, start=1):
        path = f"({hit.path})" if hit.path else "(raw DB message)"
        print(f"{i}. {hit.source_ref}  score={hit.score:.3f}  {path}")
        print(f"   {hit.excerpt}")


async def cmd_maintain(limit: int) -> int:
    from app.services.dream import process_memory_sources

    print(f"Running Dream v2 memory maintainer directly (limit={limit})...")
    async with async_session_factory() as db:
        result = await process_memory_sources(db, limit=limit)
    print(result)
    return 3 if result.get("failed", 0) else 0


def cmd_index() -> None:
    path = memory.memory_root() / memory.INDEX_FILE
    if path.is_file():
        print(path.read_text(encoding="utf-8"))
        return
    print(f"No {memory.INDEX_FILE} found at {path}")
    print(
        "Placeholder: index generation is handled by Dream when maintainer services run."
    )


async def cmd_vector_status() -> None:
    from app.services.memory_vector import get_memory_vector_backend

    backend = get_memory_vector_backend()
    print(f"backend: {backend.name}")
    print(f"enabled: {backend.enabled}")
    reason = getattr(backend, "reason", None)
    if reason:
        print(f"reason: {reason}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Manual memory v2 commands",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tree", help="Show memory/wiki tree")
    search_p = sub.add_parser(
        "search",
        help="Search memory markdown files; --raw also includes DB messages",
    )
    search_p.add_argument("query")
    search_p.add_argument("--limit", type=int, default=10)
    search_p.add_argument("--raw", action="store_true", help="Include raw DB messages")
    maintain_p = sub.add_parser("maintain", help="Run Dream maintainer directly")
    maintain_p.add_argument(
        "--limit",
        type=int,
        default=1,
        help=("Maximum pending memory sources to compile into flat wiki pages."),
    )
    sub.add_parser("index", help="Print INDEX.md or index placeholder")
    vector_p = sub.add_parser("vector", help="Inspect optional vector backend")
    vector_sub = vector_p.add_subparsers(dest="vector_cmd", required=True)
    vector_sub.add_parser("status", help="Show configured vector backend status")

    args = p.parse_args()
    if args.cmd == "tree":
        cmd_tree()
    elif args.cmd == "search":
        asyncio.run(cmd_search(args.query, limit=args.limit, raw=args.raw))
    elif args.cmd == "maintain":
        sys.exit(asyncio.run(cmd_maintain(args.limit)))
    elif args.cmd == "index":
        cmd_index()
    elif args.cmd == "vector" and args.vector_cmd == "status":
        asyncio.run(cmd_vector_status())


if __name__ == "__main__":
    main()
