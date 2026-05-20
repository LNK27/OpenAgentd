---
title: Paths & XDG Roots
description: Six XDG-aligned roots, development vs production layout, on-disk file map.
status: stable
updated: 2026-05-16
---

# Paths & XDG Roots

**Sources:** `app/core/config.py`, `app/core/paths.py`

OpenAgentd splits runtime files across **six** XDG-aligned roots, one per category of data. Each is overridable via an environment variable; all six are derived automatically from `APP_ENV` when unset.

## Roots

| Root | Env var | Production default | Development default | Sandbox |
|------|---------|--------------------|---------------------|---------|
| Data | `OPENAGENTD_DATA_DIR` | `~/.local/share/openagentd` | `.openagentd/data` | denied |
| Config | `OPENAGENTD_CONFIG_DIR` | `~/.config/openagentd` | `.openagentd/config` | allowed |
| State | `OPENAGENTD_STATE_DIR` | `~/.local/state/openagentd` | `.openagentd/state` | denied |
| Cache | `OPENAGENTD_CACHE_DIR` | `~/.cache/openagentd` | `.openagentd/cache` | denied |
| Workspace | `OPENAGENTD_WORKSPACE_DIR` | `~/.local/share/openagentd-workspace` | `.openagentd/workspace` | allowed |
| Wiki | `OPENAGENTD_WIKI_DIR` | `~/.local/share/openagentd-wiki` | `.openagentd/wiki` | allowed |

**What lives where:**

- **Data** — irreplaceable user data. SQLite DB (`openagentd.db`). **Back this up.**
- **Config** — hand-edited configuration. Agents (`agents/`), skills (`skills/`), runtime settings (`settings.yaml`), generation config (`multimodal.yaml`), voice (`speech.yaml`), MCP (`mcp.json`), sandbox (`sandbox.yaml`), `.env`. (Summarisation has no file-based config — all tuning lives in `app/agent/hooks/summarization.py`.)
- **State** — historical bookkeeping. Logs (`logs/`), telemetry (`telemetry/`), OTEL rollups (`otel/`), `openagentd.pid`. Safe to archive.
- **Cache** — regeneratable throwaway. `quoteoftheday.json`, `copilot_oauth.json`, `codex_oauth.json`. Safe to delete any time.
- **Workspace** — per-session agent workspaces (`{root}/<sid>/`). User uploads live at `{root}/<sid>/uploads/`. Allowed by the sandbox so filesystem tools (`read`/`write`/`shell`) can operate there.
- **Wiki** — agent memory (`USER.md`, `INDEX.md`, `LOG.md`, `LINT.md`, knowledge dirs, `notes/`). See [`agent/memory.md`](../agent/memory.md).

## `.env` location

Two `.env` files are loaded if present — the home-config file takes priority over the project one:

| Mode | `.env` location |
|------|-----------------|
| Production | `~/.config/openagentd/.env` |
| Development | `.env` (project root) |

## Full directory layout

Dev-mode paths shown below — substitute the production columns from the table above:

```
.openagentd/
├── data/                                  # OPENAGENTD_DATA_DIR
│   └── openagentd.db                          # main SQLite DB
├── wiki/                                  # OPENAGENTD_WIKI_DIR
│   ├── USER.md                                # pure YAML, injected into system prompt
│   ├── INDEX.md                               # dream-maintained TOC
│   ├── LOG.md                                 # service-managed dream/lint log
│   ├── LINT.md                                # latest dream lint report
│   ├── topics/                                # concept pages
│   ├── entities/                              # concrete things
│   ├── sources/                               # one page per ingested source
│   ├── comparisons/                           # X-vs-Y pages
│   └── notes/                                 # agent notes
├── workspace/                             # OPENAGENTD_WORKSPACE_DIR
│   └── {lead_session_id}/                     # per-team agent workspace
│       └── uploads/<uuid>.<ext>               # user uploads (reachable as `uploads/<filename>`)
├── config/                                # OPENAGENTD_CONFIG_DIR
│   ├── .env                                   # secrets (gitignored)
│   ├── agents/*.md                            # per-agent config
│   ├── agents/coding/*.md                     # coding-mode team
│   ├── skills/{name}/SKILL.md                 # skills
│   ├── settings.yaml                          # Dream + title generation runtime settings
│   ├── multimodal.yaml                        # image/video gen config
│   ├── speech.yaml                            # voice input config
│   ├── mcp.json                               # MCP server config
│   ├── sandbox.yaml                           # user-defined deny patterns
│   └── plugins/                               # user plugin .py drop-ins (OPENAGENTD_PLUGINS_DIRS)
├── state/                                 # OPENAGENTD_STATE_DIR
│   ├── logs/
│   │   ├── app/app.log                        # JSON app log (10 MB / 7 days)
│   │   └── sessions/{session_id}/
│   │       ├── session.log                    # human-readable per-session sink
│   │       └── {agent}.jsonl                  # structured events (SessionLogHook)
│   ├── telemetry/{session_id}/{user_msg_id}.jsonl  # context window snapshots
│   ├── snapshot/{session_id}/                 # out-of-tree git repo for /undo + /redo
│   ├── otel/                                  # OTEL spans + metrics
│   └── openagentd.pid                         # server PID file
└── cache/                                 # OPENAGENTD_CACHE_DIR
    ├── quoteoftheday.json                     # Quote of the Day cache
    ├── copilot_oauth.json                     # GitHub Copilot token
    └── codex_oauth.json                       # OpenAI Codex OAuth token
```

## Session path helpers (`app/core/paths.py`)

Backend code never constructs session paths inline. Two pure helpers return the canonical `Path` objects:

| Helper | Path | Ownership |
|--------|------|-----------|
| `workspace_dir(sid)` | `{OPENAGENTD_WORKSPACE_DIR}/{sid}` | Agent workspace root. File bytes served at `GET /api/team/{sid}/media/{path}`; flat recursive listing at `GET /api/team/{sid}/files`. |
| `uploads_dir(sid)` | `{workspace_dir(sid)}/uploads` | User uploads (flat, UUID names). Served at `GET /api/team/{sid}/uploads/{filename}`. Lives **inside** the session workspace so filesystem tools can pass uploads to workspace-bound tools as `uploads/<filename>`. |

Coding sessions use the selected project directory as the sandbox workspace. Upload storage remains under `OPENAGENTD_WORKSPACE_DIR`. `DELETE /api/team/sessions/{id}` purges the whole workspace, uploads included.

## Docker

The published image pins all path defaults under `/data`:

```
DATA=/data
CONFIG=/data/config
STATE=/data/state
CACHE=/data/cache
WORKSPACE=/data/workspace
WIKI=/data/wiki
```

`docker-compose.yaml` bind-mounts `data/`, `config/`, `wiki/`, and `workspace/` as separate host directories. See [`install.md`](../install.md) for the full setup.
