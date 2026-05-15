# OpenAgentd — Agent Instructions

On-machine AI assistant: FastAPI backend + React web UI.

## Tech stack

- **Backend:** Python 3.14, FastAPI, SQLModel, Pydantic v2, SQLite (WAL), SSE, loguru.
- **Frontend:** React 19, TypeScript 5, Vite, Bun, Tailwind v4, Zustand + Immer, TanStack Query.
- **Desktop:** Tauri v2 shell with a Python sidecar.
- **Agent config:** `.md` files with YAML frontmatter in `{OPENAGENTD_CONFIG_DIR}/agents/`.

## Layout

```
app/         FastAPI backend (agent/, api/, core/, models/, services/, cli/)
web/         React frontend
desktop/     Tauri v2 shell
seed/        Default agents, skills, mcp.json (installed by `openagentd init`)
tests/       pytest suite (mirrors app/)
documents/   Developer docs (see documents/docs/index.md)
```

## Essential commands

```bash
# Backend
uv sync                           # install
make dev                          # backend (:8000 reload) + Vite (:5173)
uv run ruff check app/ tests/     # lint
uv run ty check app/              # type check
uv run pytest --no-cov -q         # fast tests

# Frontend
cd web && bun dev                 # :5173, proxies /api → :8000
cd web && bun run lint && bun run typecheck && bun run test
```

Full command + style reference: [`documents/docs/guidelines.md`](documents/docs/guidelines.md).

## Code style (summary)

- **Python 3.14+** — `|` unions, `from __future__ import annotations`, strict type hints, Pydantic v2, absolute imports from `app`, loguru `logger.info("event key={}", val)`.
- **TypeScript** — `strict: true`, functional components with explicit props, TanStack for server state, Zustand + Immer for client state, ESM only, mobile-first design.
- **General** — thin routes, logic in services/hooks, no unnecessary abstractions, always invoke the `guidelines` skill.

## Post-implementation checklist

```bash
uv run ruff check app/ tests/ && uv run ty check app/ && uv run pytest --no-cov -q
cd web && bun run lint && bun run test              # if frontend changed
```

## Documentation

Start at [`documents/docs/index.md`](documents/docs/index.md) — it groups every doc by audience (getting-started / architecture / operations / frontend / contributing). Tracked tech debt: [`documents/techdebts/`](documents/techdebts/).
