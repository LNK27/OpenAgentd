# seed/agents/ — Agent Instructions

Seed agent profiles installed into `{OPENAGENTD_CONFIG_DIR}/agents/` by `openagentd init`.

## Where to look first

```
openagentd.md       Normal-mode lead agent seed
explorer.md         Normal-mode member seed
executor.md         Normal-mode member seed
coding/             Coding-mode team seeds
```

## Common feature checks

- Frontmatter schema: `app/agent/loader.py` and `documents/docs/configuration/agents.md`.
- Built-in first-party defaults/prompts: `app/agent/builtin_agents/` and `app/agent/builtin_prompts.py`.
- Init/copy behavior: `app/cli/init.py` and tests under `tests/cli/`.

## Rules

- Exactly one agent per team directory must have `role: lead`.
- Keep `model:` as the init-rewritten placeholder pattern used by existing seeds.
- For first-party profiles, `tools`, `skills`, and `mcp` are additive on top of code-owned defaults.
- Keep prompt bodies short and tool-agnostic; do not hardcode tool names that may be removed.
- These files are public defaults. Never include secrets or local paths.

## Checks

```bash
uv run pytest --no-cov -q tests/cli
uv run pytest --no-cov -q tests/agent/test_loader.py tests/agent/test_drift.py
```
