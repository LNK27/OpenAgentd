---
title: Skills
description: SKILL.md format, registration, and the builtin skill catalog.
status: stable
updated: 2026-05-26
---

# Skills

**Source:** `app/agent/tools/builtin/skill.py`, `app/agent/builtin_skills/`

Skills are domain-specific instruction sets that an agent loads **on demand** via the `skill` tool, rather than carrying their full text in the system prompt at all times. The framework injects only each skill's one-line `description:` into the system prompt as a registry the agent can browse.

## Layout

Each skill lives in its own subdirectory. One nested namespace level is also
supported:

```
{OPENAGENTD_CONFIG_DIR}/skills/
├── my-skill/
│   ├── SKILL.md          ← required — frontmatter + body
│   ├── creating.md       ← optional supporting files the agent can read
│   └── reference/        ← optional subdir with extra reference material
└── oad/
    └── debug/
        └── SKILL.md      ← registers as oad/debug
```

Deeper layouts such as `skills/a/b/c/SKILL.md` are ignored by discovery.

### Discovery roots

Skills are discovered from five roots in this precedence order — first match
wins on a name collision, so an OpenAgentd-native override silently shadows
the upstream or builtin copy:

| # | Root | Use it for |
|---|------|------------|
| 1 | `{cwd}/.openagentd/skills/`     | Project-specific, OpenAgentd-native |
| 2 | `{cwd}/.opencode/skills/`       | Project-specific, opencode reuse |
| 3 | `{OPENAGENTD_CONFIG_DIR}/skills/` | Your global OpenAgentd library |
| 4 | `~/.config/opencode/skills/`    | Your global opencode library (reused as-is) |
| 5 | bundled OpenAgentd skills | Read-only operational fallback shipped with the app |

`{cwd}` is the working directory the OpenAgentd server was launched from.
The Settings UI lists the same runtime-visible catalog. Non-bundled skills are
edited and deleted in place, including project-local and opencode skills.
Bundled app skills are read-only and cannot be deleted.

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
- The skill is identified by the frontmatter `name`. If absent, the directory stem is used (`my-skill` or `parent/sub`).

## Registering a skill on an agent

Add the name to `skills:` in the agent's `.md` frontmatter:

```yaml
skills:
  - my-skill
  - oad/debug
```

At startup the loader reads each listed skill's `name` + `description` and appends them to the system prompt as:

```
## Available skills

- **my-skill**: One-sentence description.

Call `skill` with the skill name to load its full instructions.
```

The `skill` tool itself is **always injected** into every agent — do not list it in `tools:`.

## Builtin skills

OpenAgentd ships these read-only operational skills inside the app package. They cannot be deleted from Settings or the skills API. A user or project skill with the same `name` overrides the builtin copy.

| Name | Purpose |
|------|---------|
| `self-healing` | Update the agent's own config on request — swap model, tune temperature/thinking, add tools/skills, change image-gen provider. |
| `skill-installer` | Install new skills from a URL or write one from scratch. |
| `mcp-installer` | Install / update / remove / restart MCP servers in `mcp.json`. |
| `plugin-installer` | Install a user plugin from a URL into `{OPENAGENTD_CONFIG_DIR}/plugins/`. |

> Other curated skills (office documents, lightpanda, etc.) are not builtin and must be installed manually via `skill-installer` or by dropping a `SKILL.md` into the skills directory.

## Authoring guidelines

- **One paragraph in `description`.** It goes into every system prompt registered with the skill — keep it tight.
- **Body is what the LLM reads when `skill(name)` is called.** Be explicit about steps, expected output, common pitfalls.
- **Supporting files** (`creating.md`, `reference/`, etc.) are reachable by the agent's filesystem tools as long as the workspace allows it — the skill body should reference them by relative path.
- **Hot reload.** `discover_skills()` is cached via `lru_cache` by an mtime signature aggregated across all discovery roots, so editing a `SKILL.md` in any user/project root — including an opencode one — is live on the next listing without a server restart.
