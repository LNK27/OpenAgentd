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
