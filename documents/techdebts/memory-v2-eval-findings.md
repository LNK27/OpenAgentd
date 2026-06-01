---
title: Memory v2 Evaluation Findings
status: active
updated: 2026-05-31
---

# Memory v2 Evaluation Findings

This log records real evaluation failures. Do not tune the benchmark to hide them.

## 2026-05-31 — Synthetic preference + abstention smoke

Dataset shape:

- 2 positive preference questions.
- 1 negative/unanswerable Kubernetes scheduler preference question.
- Retrieval mode: `wiki`.
- Corpus: `wiki/user.md` plus one deterministic Dream v2 compiled session page.

Result after removing score-threshold/boost tricks:

```json
{
  "items": 3,
  "positive_items": 2,
  "negative_items": 1,
  "recall@1": 0.5,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.75,
  "abstention_rate": 0.0,
  "false_positive_rate": 1.0,
  "failures": 1
}
```

Failure:

```text
query: What is Hoang's preferred Kubernetes scheduler plugin?
expected: abstain / no memory hit
actual hit: wiki:user
reason: lexical overlap on "Hoang" + "preferred/prefers" pulled generic user preference memory.
```

Interpretation:

- Positive retrieval is usable on this tiny smoke but not enough to claim quality.
- Negative/abstention behavior is currently weak.
- We need a real abstention/reranking policy, not benchmark-specific score hacks.
- `tests/services/test_memory_eval_regression.py` now keeps this fixture executable:
  explicit retrieval is expected to expose the false positive, while
  `MemoryContextHook` is expected to abstain for the same negative query.

Next candidates to evaluate honestly:

1. Require stronger topical overlap for automatic `MemoryContextHook` injection than for explicit `memory_search`. Initial implementation filters automatic injection by meaningful token overlap and ignores identity-only matches such as “Hoang” plus generic preference words.
2. Add source/page type hints so `wiki/user.md` generic preference pages do not answer unrelated domain-specific preference queries.
3. Add a reranker or LLM judge for automatic injection only, with citations and strict abstention instructions.
4. Keep failures in `failures.jsonl` as first-class debugging artifacts.

## 2026-05-31 — Metadata-backed automatic injection reranker

Implemented page metadata fields on deterministic Dream v2 compiled pages:

- `memory_kind`
- `scope`
- `topics`

`MemoryContextHook` now uses `topics` as a conservative automatic-injection reranker. Explicit `memory_search` remains broad and still exposes the lexical false positive; automatic injection uses topic overlap so generic preference/response-style user memory is not applied to unrelated Kubernetes scheduler questions.

This is intentionally not a benchmark-specific scoring trick:

- no query-specific thresholds were added;
- explicit retrieval metrics are unchanged and can still fail on hard negatives;
- metadata is visible in markdown frontmatter for debugging;
- missing metadata falls back to the prior lexical policy rather than hiding results globally.

## 2026-06-01 — Expanded local retrieval fixture

Moved the expanded benchmark out of unit tests and into `manual.memory_eval_fixture`, which seeds a synthetic corpus and writes 32 LongMemEval-style rows:

- 21 positive rows covering `preference`, `response_style`, `project_context`, `memory_system`, and `decision`.
- 11 negative rows covering `negative_abstention` and `domain_specific_preference`.
- Corpus: five compiled wiki pages (`wiki/user.md`, a session page, project context, Memory v2 design, and Memory v2 decisions).
- Retrieval mode: `wiki`, top-k 5.

Honest deterministic retrieval result from `manual.memory_bench` against the same fixture shape:

```json
{
  "items": 32,
  "positive_items": 21,
  "negative_items": 11,
  "recall@1": 0.8571428571428571,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.9206349206349206,
  "abstention_rate": 0.0,
  "false_positive_rate": 1.0,
  "failures": 11
}
```

Per-type summary:

| Type | Items | Positive | Negative | Recall@1 | Recall@5 | MRR@10 | Abstention | False positives | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| decision | 5 | 5 | 0 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0 |
| memory_system | 5 | 5 | 0 | 0.800 | 1.000 | 0.900 | 0.000 | 0.000 | 0 |
| preference | 3 | 3 | 0 | 0.667 | 1.000 | 0.778 | 0.000 | 0.000 | 0 |
| project_context | 6 | 6 | 0 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0 |
| response_style | 2 | 2 | 0 | 0.500 | 1.000 | 0.750 | 0.000 | 0.000 | 0 |
| domain_specific_preference | 2 | 0 | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 2 |
| negative_abstention | 9 | 0 | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 9 |

Interpretation:

- Positive retrieval is decent on this small synthetic corpus.
- Explicit lexical retrieval still cannot abstain: every negative row returns at least one hit.
- Frequent false-positive pattern: broad pages containing `Hoang`, `OpenAgentd`, `Memory v2`, or generic preference words match unrelated unanswerable questions.
- Automatic `MemoryContextHook` remains stricter than explicit retrieval; explicit benchmark failures are kept visible for future reranking/abstention work.
