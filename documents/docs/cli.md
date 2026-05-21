# CLI reference

The `openagentd` binary is the single entry point for running, managing, and inspecting the server.

## Start

```bash
openagentd                            # start in the background
```

**Flags**

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `4082` | API port |

The server runs as a detached background process. The pre-built web UI is served by FastAPI on a single port (4082). Logs go to `~/.local/state/openagentd/logs/app/app.log`. The server auto-migrates the database on startup.

If openagentd hasn't been initialised yet, `openagentd` automatically runs `openagentd init` before starting the server.

For local frontend + backend development with hot-reload, use `make dev` (from the source checkout): it starts uvicorn with `--reload` on `:8000` and Vite on `:5173` together.

---

## init

```bash
openagentd init           # interactive setup (~/.config/openagentd/)
```

Interactive first-time setup wizard. Prompts for provider, model, and API key, then installs the default agent team and editable config. Re-running `init` is safe — existing files are never overwritten.

See [Install — First run](install.md#first-run) for a full walkthrough.

---

## auth

```bash
openagentd auth copilot         # GitHub Copilot — device-flow OAuth
openagentd auth codex           # OpenAI Codex — PKCE OAuth (browser)
openagentd auth codex --device  # OpenAI Codex — headless device-code flow
openagentd auth --list          # list available OAuth providers
```

Authenticates with an OAuth-based provider. Only needed for providers that don't use an API key (GitHub Copilot, OpenAI Codex). Token is cached locally and reused on subsequent runs.

In the desktop/web UI, the same OAuth setup is available from **Settings → Providers**.

---

## migrate

```bash
openagentd migrate openclaw --model openai:gpt-5.5
openagentd migrate hermes --model openai:gpt-5.5
```

Imports OpenClaw or Hermes identity/context Markdown files into one OpenAgentd lead agent. Use `--from`, `--name`, `--config-dir`, and `--force` to override defaults.

See [`../../MIGRATION.md`](../../MIGRATION.md) for source files, output paths, and manual migration notes for Claude Code and Codex CLI.

---

## stop

```bash
openagentd stop
```

Sends `SIGTERM` to the background server process. Waits up to 5 seconds for a clean shutdown, then sends `SIGKILL` if needed. Clears the PID file.

---

## status

```bash
openagentd status
```

Reports whether a background server is running, the PIDs, and the log file path.

---

## logs

```bash
openagentd logs           # tail last 50 lines and follow
openagentd logs -n 100    # tail last 100 lines and follow
```

Tails the server log file (equivalent to `tail -n <lines> -f`). Reads from `~/.local/state/openagentd/logs/app/app.log`.

---

## doctor

```bash
openagentd doctor
```

Runs a series of health checks and exits with code 1 if any fail:

| Check | Pass | Fail |
|---|---|---|
| Python version | ≥ 3.14 | < 3.14 |
| API key / OAuth | Any provider key set, or OAuth-only provider (`copilot`, `codex`, `vertexai`, `cliproxy`, `router9`, `ollama`) configured | No key and no OAuth provider found |
| Provider/key match | Lead agent's provider has a matching key (or is OAuth-only) | Provider set but key missing |
| Database | `openagentd.db` exists | Not found (warning only — created on first run) |
| Alembic config | `alembic.ini` next to `app/core/db.py` | Missing (reinstall) |
| Port 4082 | Available | In use |
| Web UI | Bundled `_web_dist/` present | Missing (warning only) |
| Agents directory | At least one `.md` in `{OPENAGENTD_CONFIG_DIR}/agents/` | Missing (run `openagentd init`) |

Warnings (degraded but bootable) don't affect the exit code. Run this first when something looks wrong.

---

## update / upgrade

```bash
openagentd upgrade   # preferred
openagentd update    # alias
```

Upgrades openagentd to the latest published version. Detects how openagentd was installed and delegates to the right package manager:

| Install method | Command run |
|---|---|
| Homebrew | `brew upgrade openagentd` |
| uv tool | `uv tool upgrade openagentd` |
| pipx | `pipx upgrade openagentd` |
| pip (fallback) | `pip install --upgrade openagentd` |

The desktop bundle has its own update path — **OpenAgentd → Check for Updates…** in the menu bar — backed by `tauri-plugin-updater` against a signed minisign manifest, not the PyPI flow above.

---

## version

```bash
openagentd version
openagentd --version
```

Prints the installed version and exits.

---

## Related

- [Install](install.md)
- [Configuration](configuration.md)
- [Troubleshooting](troubleshooting.md)
