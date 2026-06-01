"""Seed a synthetic Memory v2 eval corpus and dataset.

This script is for manual benchmark runs, not unit tests. It creates a small
LongMemEval-style JSONL dataset plus matching compiled `wiki/*.md` pages in the
configured `OPENAGENTD_WIKI_DIR`.

Usage:
  uv run python -m manual.memory_eval_fixture
  uv run python -m manual.memory_eval_fixture --run
  OPENAGENTD_WIKI_DIR=/tmp/memory uv run python -m manual.memory_eval_fixture --data /tmp/memory-eval.jsonl --run
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.services.memory import seed_memory, write_memory_file
from manual.memory_bench import cmd_longmemeval

DEFAULT_DATA_PATH = Path(".openagentd/evals/fixtures/memory-v2-expanded.jsonl")


def _user_memory_page(body: str) -> str:
    return (
        "---\n"
        "description: User preferences\n"
        "memory_kind: profile\n"
        "scope: user\n"
        "topics: [preferences, response-style, personalization]\n"
        "---\n\n"
        f"# User\n\n## Facts\n\n{body}"
    )


def _memory_page(
    title: str,
    body: str,
    *,
    memory_kind: str,
    scope: str,
    topics: list[str],
) -> str:
    return (
        "---\n"
        f"description: {title}\n"
        f"memory_kind: {memory_kind}\n"
        f"scope: {scope}\n"
        f"topics: {topics}\n"
        "confidence: medium\n"
        "---\n\n"
        f"# {title}\n\n## Facts\n\n{body}"
    )


def seed_eval_corpus() -> None:
    """Write the synthetic compiled wiki pages used by the fixture."""
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        _user_memory_page(
            "- Hoang prefers direct fact-based answers and wants implicit personalization. "
            "[session:00000000-0000-0000-0000-000000000001]\n"
        ),
    )
    write_memory_file(
        "wiki/session-local.md",
        _memory_page(
            "session:local",
            "- OpenAgentd Memory v2 should help through implicit personalization "
            "without repeated reminders. "
            "[session:00000000-0000-0000-0000-000000000002]",
            memory_kind="conversation",
            scope="session",
            topics=["openagentd", "memory", "personalization"],
        ),
    )
    write_memory_file(
        "wiki/project-openagentd.md",
        _memory_page(
            "OpenAgentd project context",
            "- OpenAgentd is Hoang's main project. "
            "[session:00000000-0000-0000-0000-000000000003]\n"
            "- OpenAgentd is a Tauri 2 desktop shell wrapping a FastAPI backend "
            "and React web UI. [session:00000000-0000-0000-0000-000000000003]\n"
            "- Python 3.14, React 19, Vite 7, Bun, Tailwind v4, SQLite WAL, "
            "and SQLModel are important OpenAgentd stack choices. "
            "[session:00000000-0000-0000-0000-000000000003]",
            memory_kind="project_context",
            scope="project",
            topics=["openagentd", "project", "stack", "fastapi", "react"],
        ),
    )
    write_memory_file(
        "wiki/memory-v2.md",
        _memory_page(
            "Memory v2 design",
            "- Memory v2 keeps a simple Karpathy-style markdown wiki. "
            "[session:00000000-0000-0000-0000-000000000004]\n"
            "- Dream is the Memory v2 maintainer. "
            "[session:00000000-0000-0000-0000-000000000004]\n"
            "- DB messages remain canonical raw sources for chat memory. "
            "[session:00000000-0000-0000-0000-000000000004]\n"
            "- Memory v2 uses deterministic token-overlap retrieval first, with "
            "honest LongMemEval and LoCoMo-style evals instead of benchmark tricks. "
            "[session:00000000-0000-0000-0000-000000000004]",
            memory_kind="memory_system",
            scope="project",
            topics=["memory", "dream", "retrieval", "evals", "karpathy"],
        ),
    )
    write_memory_file(
        "wiki/decisions.md",
        _memory_page(
            "Memory v2 decisions",
            "- Breaking changes are allowed for Memory v2. "
            "[session:00000000-0000-0000-0000-000000000005]\n"
            "- Migration revision 00000009 must follow 00000008 and must not "
            "duplicate 00000005. [session:00000000-0000-0000-0000-000000000005]\n"
            "- Turbovec is only a future candidate semantic backend, not the "
            "default MVP. [session:00000000-0000-0000-0000-000000000005]\n"
            "- Source citations should stay attached to promoted facts, for "
            "example [session:11111111-1111-1111-1111-111111111111]. "
            "[session:00000000-0000-0000-0000-000000000005]\n"
            "- The current decision is that Memory v2 has no mandatory root USER.md "
            "taxonomy. [session:00000000-0000-0000-0000-000000000005]\n"
            "- A later session changed the maintainer name from WikiBot to Dream. "
            "[session:00000000-0000-0000-0000-000000000006]\n\n"
            "## Conflicts / stale candidates\n\n"
            "- A stale candidate once said USER.md was mandatory. "
            "[session:00000000-0000-0000-0000-000000000000]",
            memory_kind="decision",
            scope="project",
            topics=[
                "memory",
                "migration",
                "turbovec",
                "decision",
                "citations",
                "stale",
            ],
        ),
    )


def fixture_rows() -> list[dict[str, Any]]:
    """Return the synthetic LongMemEval-style fixture rows."""
    return [
        {
            "id": "pref-style",
            "type": "response_style",
            "question": "How should the assistant respond to Hoang?",
            "answers": ["direct fact-based answers"],
        },
        {
            "id": "memory-goal",
            "type": "preference",
            "question": "What does Hoang want memory to do?",
            "answers": ["implicit personalization"],
        },
        {
            "id": "pref-dialogue-detail",
            "type": "response_style",
            "question": "What answer style does Hoang prefer?",
            "answers": ["direct fact-based answers"],
        },
        {
            "id": "pref-personalization",
            "type": "preference",
            "question": "What kind of personalization should memory support?",
            "answers": ["implicit personalization"],
        },
        {
            "id": "project-main",
            "type": "project_context",
            "question": "What is Hoang's main project?",
            "answers": ["OpenAgentd"],
        },
        {
            "id": "project-shell",
            "type": "project_context",
            "question": "What desktop shell does OpenAgentd use?",
            "answers": ["Tauri 2 desktop shell"],
        },
        {
            "id": "project-backend",
            "type": "project_context",
            "question": "What backend framework does OpenAgentd use?",
            "answers": ["FastAPI backend"],
        },
        {
            "id": "project-frontend",
            "type": "project_context",
            "question": "What frontend stack does OpenAgentd use?",
            "answers": ["React web UI"],
        },
        {
            "id": "project-python",
            "type": "project_context",
            "question": "Which Python version matters for OpenAgentd?",
            "answers": ["Python 3.14"],
        },
        {
            "id": "project-tailwind",
            "type": "project_context",
            "question": "Which Tailwind version is part of OpenAgentd's frontend?",
            "answers": ["Tailwind v4"],
        },
        {
            "id": "memory-style",
            "type": "memory_system",
            "question": "What style of wiki should Memory v2 use?",
            "answers": ["Karpathy-style markdown wiki"],
        },
        {
            "id": "memory-maintainer",
            "type": "memory_system",
            "question": "What is the Memory v2 maintainer called?",
            "answers": ["Dream"],
        },
        {
            "id": "memory-raw-source",
            "type": "memory_system",
            "question": "What remains the canonical raw source for chat memory?",
            "answers": ["DB messages remain canonical raw sources"],
        },
        {
            "id": "memory-retrieval-baseline",
            "type": "memory_system",
            "question": "What retrieval baseline does Memory v2 start with?",
            "answers": ["deterministic token-overlap retrieval"],
        },
        {
            "id": "memory-evals",
            "type": "memory_system",
            "question": "Which eval styles should Memory v2 use honestly?",
            "answers": ["LongMemEval and LoCoMo-style evals"],
        },
        {
            "id": "decision-breaking",
            "type": "decision",
            "question": "Are breaking changes allowed for Memory v2?",
            "answers": ["Breaking changes are allowed"],
        },
        {
            "id": "decision-migration",
            "type": "decision",
            "question": "Which migration revision must Memory v2 use?",
            "answers": ["00000009"],
        },
        {
            "id": "decision-migration-after",
            "type": "decision",
            "question": "Which migration revision must 00000009 follow?",
            "answers": ["00000008"],
        },
        {
            "id": "decision-no-dup",
            "type": "decision",
            "question": "Which migration revision must not be duplicated?",
            "answers": ["00000005"],
        },
        {
            "id": "decision-turbovec",
            "type": "decision",
            "question": "What is Turbovec's role in Memory v2?",
            "answers": ["future candidate semantic backend"],
        },
        {
            "id": "citation-preserved",
            "type": "citation_correctness",
            "question": "Which source citation is attached to the Memory v2 promoted fact example?",
            "answers": ["session:11111111-1111-1111-1111-111111111111"],
        },
        {
            "id": "stale-user-md",
            "type": "stale_fact",
            "question": "What is the current decision about mandatory root USER.md taxonomy?",
            "answers": ["no mandatory root USER.md taxonomy"],
        },
        {
            "id": "temporal-maintainer",
            "type": "temporal_context",
            "question": "After the later session, what is the Memory v2 maintainer called?",
            "answers": ["Dream"],
        },
        {
            "id": "raw-session-personalization",
            "type": "preference",
            "question": "What should OpenAgentd Memory v2 help through without repeated reminders?",
            "answers": ["implicit personalization without repeated reminders"],
        },
        {
            "id": "scheduler-negative",
            "type": "domain_specific_preference",
            "question": "What is Hoang's preferred Kubernetes scheduler plugin?",
            "negative": True,
        },
        {
            "id": "database-negative",
            "type": "negative_abstention",
            "question": "What is Hoang's preferred production Postgres extension?",
            "negative": True,
        },
        {
            "id": "color-negative",
            "type": "negative_abstention",
            "question": "What is Hoang's favorite UI accent color?",
            "negative": True,
        },
        {
            "id": "browser-negative",
            "type": "negative_abstention",
            "question": "Which browser does Hoang prefer for manual smoke testing?",
            "negative": True,
        },
        {
            "id": "llm-negative",
            "type": "negative_abstention",
            "question": "Which LLM provider did Hoang choose for Dream synthesis?",
            "negative": True,
        },
        {
            "id": "scheduler-plugin-negative",
            "type": "domain_specific_preference",
            "question": "Which Kubernetes scheduler plugin should OpenAgentd remember for Hoang?",
            "negative": True,
        },
        {
            "id": "cloud-negative",
            "type": "negative_abstention",
            "question": "Which cloud region does Hoang prefer for OpenAgentd deployments?",
            "negative": True,
        },
        {
            "id": "vector-db-negative",
            "type": "negative_abstention",
            "question": "Which vector database is the Memory v2 default?",
            "negative": True,
        },
        {
            "id": "ontology-negative",
            "type": "negative_abstention",
            "question": "Which mandatory ontology database backs Memory v2?",
            "negative": True,
        },
        {
            "id": "raw-copy-negative",
            "type": "negative_abstention",
            "question": "Where are raw session markdown copies required under raw/sessions?",
            "negative": True,
        },
    ]


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in fixture_rows()) + "\n",
        encoding="utf-8",
    )


async def _run(args: argparse.Namespace) -> None:
    seed_eval_corpus()
    write_fixture(args.data)
    print(f"Wrote fixture data: {args.data}")
    if args.run:
        await cmd_longmemeval(
            mode=args.mode,
            limit=args.limit,
            top_k=args.top_k,
            data=args.data,
            debug_hits=args.debug_hits,
            write_candidates=args.write_candidates,
        )
    else:
        print(
            "Run benchmark with: "
            f"uv run python -m manual.memory_bench longmemeval --mode {args.mode} "
            f"--top-k {args.top_k} --data {args.data}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--run", action="store_true", help="Run memory_bench after seeding"
    )
    parser.add_argument(
        "--mode",
        choices=("wiki", "raw", "wiki-plus-raw", "injection"),
        default="wiki",
        help="Benchmark retrieval mode when --run is set",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--debug-hits", action="store_true")
    parser.add_argument("--write-candidates", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
