# seed/skills/ — Agent Instructions

Seed skills copied to `{OPENAGENTD_CONFIG_DIR}/skills/` for new installs.

## Where to look first

```
<skill>/SKILL.md    Skill instructions loaded into agent context
mcp-installer/      Built-in skill for MCP server management
```

## Common feature checks

- Skill loading/runtime behavior: inspect `app/agent/builtin_skills/`, skill-related loader code, and tests under `tests/agent/`.
- User-facing skill docs: `documents/docs/configuration/skills.md`.
- Seed install behavior: `app/cli/init.py` and `seed/README.md`.

## Rules

- Keep every skill self-contained in its own directory.
- `SKILL.md` should include exact paths, file formats, and operational rules the agent needs later.
- Avoid secrets, machine-specific paths, or commands that require interactive input.
- Prefer concise, task-oriented instructions over broad background.

## Checks

```bash
uv run pytest --no-cov -q tests/cli
uv run ruff check app/ tests/
```
