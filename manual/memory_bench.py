"""LongMemEval retrieval harness skeleton for memory experiments.

No datasets are downloaded by this script.  Pass a local JSON/JSONL file with
``--data``.  The parser accepts common fields such as question/query/input and
answer/answers/evidence/reference. Rows may include ``type`` or
``question_type`` for grouped metrics. Negative/abstention rows are supported
with ``negative: true``, ``answerable: false``, ``should_answer: false``,
``abstain: true``, or an empty answer list.

This is a deterministic token-overlap baseline harness for iterative local
evals, not an official benchmark downloader/runner.

Usage:
  uv run python -m manual.memory_bench longmemeval --mode raw --limit 20 --top-k 10 --data PATH
  uv run python -m manual.memory_bench longmemeval --mode wiki --limit 20 --top-k 10 --data PATH
  uv run python -m manual.memory_bench longmemeval --mode wiki-plus-raw --limit 20 --top-k 10 --data PATH
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.db import async_session_factory
from app.services import memory

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]*", re.IGNORECASE)


@dataclass(frozen=True)
class BenchItem:
    id: str
    query: str
    answers: list[str]
    question_type: str
    is_negative: bool


@dataclass(frozen=True)
class RetrievalHit:
    source: str
    score: float
    text: str


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "examples", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [data]
    raise ValueError(
        "Expected JSONL rows, a JSON list, or a JSON object with data/examples/items"
    )


def _coerce_items(path: Path, *, limit: int | None) -> list[BenchItem]:
    rows = _load_rows(path)
    items: list[BenchItem] = []
    for i, row in enumerate(rows):
        query = (
            row.get("question")
            or row.get("query")
            or row.get("input")
            or row.get("prompt")
        )
        if not isinstance(query, str) or not query.strip():
            continue
        raw_answers = (
            row.get("answers")
            or row.get("answer")
            or row.get("evidence")
            or row.get("reference")
            or []
        )
        if isinstance(raw_answers, str):
            answers = [raw_answers]
        elif isinstance(raw_answers, list):
            answers = [str(a) for a in raw_answers if str(a).strip()]
        else:
            answers = []
        item_id = str(row.get("id") or row.get("question_id") or i)
        question_type = str(
            row.get("question_type") or row.get("type") or "unknown"
        ).strip()
        is_negative = _is_negative_row(row, answers)
        items.append(
            BenchItem(
                id=item_id,
                query=query.strip(),
                answers=answers,
                question_type=question_type or "unknown",
                is_negative=is_negative,
            )
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def _is_negative_row(row: dict[str, Any], answers: list[str]) -> bool:
    for key in ("negative", "abstain"):
        if isinstance(row.get(key), bool) and row[key]:
            return True
    for key in ("answerable", "should_answer"):
        if isinstance(row.get(key), bool) and not row[key]:
            return True
    return not answers


async def _retrieve(query: str, *, mode: str, top_k: int) -> list[RetrievalHit]:
    """Run the same deterministic retrieval service used by `memory_search`."""
    if mode == "wiki":
        results = memory.search_memory_files(query, limit=top_k, scope="compiled")
    else:
        async with async_session_factory() as db:
            if mode == "raw":
                results = await memory.search_memory_messages(db, query, limit=top_k)
            else:
                results = await memory.memory_search(query, db=db, limit=top_k)
    return [
        RetrievalHit(
            source=result.source_ref,
            score=result.score,
            text=result.excerpt
            if result.path is None
            else memory.read_memory_file(result.path).content,
        )
        for result in results
    ]


def _contains_answer(hits: list[RetrievalHit], answers: list[str], *, k: int) -> bool:
    if not answers:
        return False
    haystack = "\n".join(h.text.lower() for h in hits[:k])
    return any(answer.lower() in haystack for answer in answers if answer)


def _reciprocal_rank(
    hits: list[RetrievalHit], answers: list[str], *, max_k: int = 10
) -> float:
    if not answers:
        return 0.0
    lowered = [a.lower() for a in answers if a]
    for rank, hit in enumerate(hits[:max_k], start=1):
        text = hit.text.lower()
        if any(answer in text for answer in lowered):
            return 1.0 / rank
    return 0.0


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _empty_stats() -> dict[str, float | int]:
    return {
        "items": 0,
        "positive_items": 0,
        "negative_items": 0,
        "recall@1_hits": 0,
        "recall@5_hits": 0,
        "recall@10_hits": 0,
        "mrr@10_total": 0.0,
        "abstention_hits": 0,
        "false_positives": 0,
        "failures": 0,
    }


def _record_item(
    stats: dict[str, float | int],
    *,
    item: BenchItem,
    hits: list[RetrievalHit],
    rr: float,
) -> bool:
    stats["items"] += 1
    if item.is_negative:
        stats["negative_items"] += 1
        abstained = not hits
        stats["abstention_hits"] += int(abstained)
        stats["false_positives"] += int(not abstained)
        stats["failures"] += int(not abstained)
        return abstained

    stats["positive_items"] += 1
    for k in (1, 5, 10):
        stats[f"recall@{k}_hits"] += int(_contains_answer(hits, item.answers, k=k))
    stats["mrr@10_total"] += rr
    passed = rr > 0.0
    stats["failures"] += int(not passed)
    return passed


def _finalize_stats(stats: dict[str, float | int]) -> dict[str, float | int]:
    positive = int(stats["positive_items"])
    negative = int(stats["negative_items"])
    return {
        "items": stats["items"],
        "positive_items": positive,
        "negative_items": negative,
        "recall@1": stats["recall@1_hits"] / positive if positive else 0.0,
        "recall@5": stats["recall@5_hits"] / positive if positive else 0.0,
        "recall@10": stats["recall@10_hits"] / positive if positive else 0.0,
        "mrr@10": stats["mrr@10_total"] / positive if positive else 0.0,
        "abstention_rate": stats["abstention_hits"] / negative if negative else 0.0,
        "false_positive_rate": stats["false_positives"] / negative if negative else 0.0,
        "failures": stats["failures"],
    }


async def cmd_longmemeval(
    *, mode: str, limit: int | None, top_k: int, data: Path
) -> None:
    run_dir = Path(".openagentd/evals/runs") / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    run_dir.mkdir(parents=True, exist_ok=False)

    config = {
        "benchmark": "longmemeval",
        "mode": mode,
        "limit": limit,
        "top_k": top_k,
        "data": str(data),
    }
    _write_json(run_dir / "config.json", config)

    items = _coerce_items(data, limit=limit)
    overall = _empty_stats()
    by_type: dict[str, dict[str, float | int]] = {}
    with (
        (run_dir / "results.jsonl").open("w", encoding="utf-8") as results_f,
        (run_dir / "failures.jsonl").open("w", encoding="utf-8") as failures_f,
    ):
        for item in items:
            hits = await _retrieve(item.query, mode=mode, top_k=top_k)
            record = {
                "id": item.id,
                "query": item.query,
                "answers": item.answers,
                "type": item.question_type,
                "negative": item.is_negative,
                "hits": [asdict(h) for h in hits],
            }
            rr = _reciprocal_rank(hits, item.answers)
            passed = _record_item(overall, item=item, hits=hits, rr=rr)
            type_stats = by_type.setdefault(item.question_type, _empty_stats())
            _record_item(type_stats, item=item, hits=hits, rr=rr)
            record["reciprocal_rank@10"] = rr
            record["passed"] = passed
            results_f.write(json.dumps(record, sort_keys=True) + "\n")
            if not passed:
                failures_f.write(json.dumps(record, sort_keys=True) + "\n")

    metrics = _finalize_stats(overall)
    metrics["by_type"] = {
        question_type: _finalize_stats(stats)
        for question_type, stats in sorted(by_type.items())
    }
    _write_json(run_dir / "metrics.json", metrics)
    report = "\n".join(
        [
            "# LongMemEval retrieval run",
            "",
            f"- Mode: `{mode}`",
            f"- Items: {metrics['items']}",
            f"- Positive items: {metrics['positive_items']}",
            f"- Negative/abstention items: {metrics['negative_items']}",
            f"- Top K: {top_k}",
            f"- Recall@1: {metrics['recall@1']:.3f}",
            f"- Recall@5: {metrics['recall@5']:.3f}",
            f"- Recall@10: {metrics['recall@10']:.3f}",
            f"- MRR@10: {metrics['mrr@10']:.3f}",
            f"- Abstention rate: {metrics['abstention_rate']:.3f}",
            f"- False positive rate: {metrics['false_positive_rate']:.3f}",
            f"- Failures: {metrics['failures']}",
            "",
            "## Per-type metrics",
            "",
            *_format_type_metrics(metrics["by_type"]),
            "",
        ]
    )
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"Wrote run: {run_dir}")


def _format_type_metrics(by_type: object) -> list[str]:
    if not isinstance(by_type, dict) or not by_type:
        return ["(none)"]
    lines = [
        "| Type | Items | Positives | Negatives | Recall@10 | MRR@10 | Abstention | False positives | Failures |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for question_type, raw in by_type.items():
        if not isinstance(raw, dict):
            continue
        lines.append(
            "| "
            f"{question_type} | {raw['items']} | {raw['positive_items']} | "
            f"{raw['negative_items']} | {raw['recall@10']:.3f} | "
            f"{raw['mrr@10']:.3f} | {raw['abstention_rate']:.3f} | "
            f"{raw['false_positive_rate']:.3f} | {raw['failures']} |"
        )
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description="Memory retrieval benchmark harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    lm = sub.add_parser("longmemeval", help="Run LongMemEval-style retrieval skeleton")
    lm.add_argument("--mode", choices=("raw", "wiki", "wiki-plus-raw"), required=True)
    lm.add_argument("--limit", type=int, default=None)
    lm.add_argument("--top-k", type=int, default=10)
    lm.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Local JSON/JSONL dataset; no downloads are performed",
    )

    args = p.parse_args()
    if args.cmd == "longmemeval":
        asyncio.run(
            cmd_longmemeval(
                mode=args.mode, limit=args.limit, top_k=args.top_k, data=args.data
            )
        )


if __name__ == "__main__":
    main()
