---
title: Skills
description: SKILL.md format, registration, and the seeded skill catalog.
status: stable
updated: 2026-05-16
---

# Skills

**Source:** `app/agent/tools/builtin/skill.py`, `seed/skills/`

Skills are domain-specific instruction sets that an agent loads **on demand** via the `skill` tool, rather than carrying their full text in the system prompt at all times. The framework injects only each skill's one-line `description:` into the system prompt as a registry the agent can browse.

## Layout

Each skill lives in its own subdirectory under `{OPENAGENTD_CONFIG_DIR}/skills/`:

```
{OPENAGENTD_CONFIG_DIR}/skills/
└── my-skill/
    ├── SKILL.md          ← required — frontmatter + body
    ├── creating.md       ← optional supporting files the agent can read
    └── reference/        ← optional subdir with extra reference material
```

`SKILL.md` follows this layout:

```markdown
---
name: my-skill
description: >-
  One-sentence description shown in the system prompt registry.
---

# My Skill

The full instructions the agent reads when it calls `skill("my-skill")`.
```

- The frontmatter is **not** returned to the agent — only the body below.
- The skill is identified by the frontmatter `name`. If absent, the subdirectory name is used.

## Registering a skill on an agent

Add the name to `skills:` in the agent's `.md` frontmatter:

```yaml
skills:
  - my-skill
```

At startup the loader reads each listed skill's `name` + `description` and appends them to the system prompt as:

```
## Available skills

- **my-skill**: One-sentence description.

Call `skill` with the skill name to load its full instructions.
```

The `skill` tool itself is **always injected** into every agent — do not list it in `tools:`.

## Seeded skills

`openagentd init` copies these from `seed/skills/` into `{OPENAGENTD_CONFIG_DIR}/skills/`. Each is a working example of the format and a useful capability on its own.

| Name | Purpose |
|------|---------|
| `web-research` | Efficient web research methodology: targeted search, source verification, structured findings with confidence levels. |
| `self-healing` | Update the agent's own config on request — swap model, tune temperature/thinking, add tools/skills, change image-gen provider. |
| `skill-installer` | Install new skills from a URL or write one from scratch. |
| `mcp-installer` | Install / update / remove / restart MCP servers in `mcp.json`. |
| `plugin-installer` | Install a user plugin from a URL into `{OPENAGENTD_CONFIG_DIR}/plugins/`. |

> Other curated skills (office documents, lightpanda, etc.) are not currently part of the bundled seed and must be installed manually via `skill-installer` or by dropping a `SKILL.md` into the skills directory.

## Authoring guidelines

- **One paragraph in `description`.** It goes into every system prompt registered with the skill — keep it tight.
- **Body is what the LLM reads when `skill(name)` is called.** Be explicit about steps, expected output, common pitfalls.
- **Supporting files** (`creating.md`, `reference/`, etc.) are reachable by the agent's filesystem tools as long as the workspace allows it — the skill body should reference them by relative path.
- **Hot reload.** `discover_skills()` is cached via `lru_cache` by directory mtime, so saving a `SKILL.md` is live on the next listing without a server restart.
