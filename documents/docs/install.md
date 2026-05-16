# Install

openagentd ships as a single Python package that includes the pre-built web UI. No Node, no Bun, no separate frontend process — one process, one port.

## uv (recommended)

```bash
uv tool install openagentd
```

Installs `openagentd` into an isolated tool venv managed by [uv](https://docs.astral.sh/uv/), and puts the binary on your `PATH`. This is the recommended path on every OS.

## pipx

```bash
pipx install openagentd
```

Same isolation model as `uv tool`, slower install. Use this if you already have pipx and don't want another tool.

## pip

```bash
pip install --user openagentd
```

Works on Linux distros and Python builds without [PEP 668](https://peps.python.org/pep-0668/) protection. On **macOS Homebrew Python**, **Debian/Ubuntu system Python**, and most modern distros, `pip install` will refuse with an `externally-managed-environment` error — use `uv tool install` or `pipx install` above instead, or create a venv first.

## Homebrew (macOS / Linux)

```bash
brew install lthoangg/tap/openagentd
```

The `lthoangg/tap/` prefix auto-taps the formula on first install — no separate `brew tap` step needed. To upgrade:

```bash
openagentd upgrade      # via the built-in upgrade command
# or directly:
brew upgrade openagentd
```

> **Note:** On first install or after a `brew reinstall`, you may see a warning about
> `Failed changing dylib ID` for the `cryptography` package. This is a cosmetic Homebrew
> relinking warning — openagentd still works correctly. Run `brew update` before
> reinstalling to ensure the latest formula is used.

## Desktop app

A native double-click installer for users who don't want a terminal. The desktop build is a [Tauri 2](https://tauri.app) shell that launches a bundled Python sidecar — same backend, same web UI, no port to remember.

Grab the latest installer from the [desktop releases](https://github.com/lthoangg/openagentd/releases?q=desktop):

| Platform | Artefact | Size |
|---|---|---|
| macOS (Apple Silicon, 11+) | `OpenAgentd_*_aarch64.dmg` or `OpenAgentd_*.app.tar.gz` | ~180 MB |
| Windows 10/11 (x64) | `OpenAgentd_*_x64-setup.exe` (NSIS) or `OpenAgentd_*_x64_en-US.msi` | ~150 MB |
| Linux (x64) | `OpenAgentd_*_amd64.AppImage` or `OpenAgentd_*_amd64.deb` | ~160 MB |

### Why is it unsigned? <a id="desktop-unsigned"></a>

OpenAgentd ships **without** an Apple Developer ID signature or a Windows Authenticode certificate. Both are paid subscriptions ($99/yr Apple, $300+ Windows EV) that we've chosen not to buy yet. The binary is exactly what came out of CI — reproducible from the [`release-desktop.yml`](https://github.com/lthoangg/openagentd/blob/main/.github/workflows/release-desktop.yml) workflow on a public GitHub-hosted runner — but the OS treats it the same as any unsigned executable.

That means:

- **macOS:** Gatekeeper rejects the bundle on first launch with `"OpenAgentd.app" is damaged and can't be opened`. The bundled `install.sh` works around this by stripping the quarantine xattr and ad-hoc signing the app *with your own machine as the signer*. This is the same workaround used by every open-source macOS app you compile yourself.
- **Windows:** SmartScreen warns `Windows protected your PC` on first launch. Click **More info → Run anyway** once; subsequent launches are silent.
- **Linux:** No code-signing equivalent — the AppImage / .deb just runs.

The Tauri auto-updater is a separate signing chain. Update payloads are signed with a minisign key we control (public half embedded in the app, private half in GitHub secrets), so even though the OS thinks the app is unsigned, **updates themselves are cryptographically verified**.

### macOS install

The easiest path is the Homebrew cask — it handles the quarantine + ad-hoc signing automatically on every install and upgrade:

```sh
brew install --cask lthoangg/tap/openagentd
# upgrades later: brew upgrade --cask openagentd
```

The `.dmg` path is for users who don't want Homebrew:

```sh
# Mount the .dmg, then run the bundled installer from inside the volume.
hdiutil attach OpenAgentd_*_aarch64.dmg
cd /Volumes/OpenAgentd*
./install.sh               # ad-hoc signs the bundle and exits
./install.sh --install     # also copies to /Applications
```

On first launch via the `.dmg` path, **right-click `OpenAgentd.app` → Open** (single-click won't work the first time — that's by design). The cask path handles this for you. Subsequent launches are normal.

If you skip `install.sh` and just drag-to-Applications, you'll hit the `"damaged"` error. Re-run `install.sh` against the installed bundle to fix it:

```sh
./install.sh /Applications/OpenAgentd.app --force
```

### Windows install

Double-click `OpenAgentd_*_x64-setup.exe`. When SmartScreen warns:

1. Click **More info**.
2. Click **Run anyway**.
3. Step through the NSIS installer.

The MSI variant (`OpenAgentd_*_x64_en-US.msi`) is for managed deployments (group policy / `msiexec /i ... /quiet`).

### Linux install

```sh
chmod +x OpenAgentd_*_amd64.AppImage
./OpenAgentd_*_amd64.AppImage            # run directly
```

Or use the bundled `install.sh` for a launcher entry:

```sh
./install.sh --install                   # copies to ~/.local/bin, drops a .desktop file
```

The `.deb` package works on Debian/Ubuntu derivatives: `sudo dpkg -i OpenAgentd_*_amd64.deb`. AppImage is preferred — self-contained, no system-level changes, runs on any glibc 2.28+ distro.

### Auto-updates

Open **Settings → Application update → Check for updates** to check the rolling [`latest-desktop/latest.json`](https://github.com/lthoangg/openagentd/releases/download/latest-desktop/latest.json) manifest. When a new version is offered, the **Install** button downloads, verifies the minisign signature, stages the new bundle, and restarts the app. An invalid signature aborts the install with a toast — no silent overwrites.

The same Settings card hosts the legacy PyPI-based update path when OpenAgentd is running as a CLI server outside the desktop bundle; the UI picks the right path automatically based on `window.__TAURI_INTERNALS__`.

## Docker

```bash
git clone https://github.com/lthoangg/openagentd.git
cd openagentd
cp .env.example .env              # add your API key(s)

docker compose up -d              # pulls and starts on http://localhost:4082
```

`docker-compose.yaml` bind-mounts four host directories so data is inspectable and portable:

| Host path | Container path | Contents |
|-----------|---------------|----------|
| `./data` | `/data` | SQLite DB — **back this up** |
| `./config` | `/data/config` | `agents/`, `skills/`, `.env`, `mcp.json` |
| `./wiki` | `/data/wiki` | `USER.md`, `topics/`, `notes/` |
| `./workspace` | `/data/workspace` | Per-session agent workspaces |

The directories are created automatically by Docker on first start. To pre-load agents or skills, populate `./config/agents/` before running `docker compose up`.

Or pull and run without Compose:

```bash
docker run --env-file .env -p 4082:4082 \
  -v "$PWD/data:/data" \
  -v "$PWD/config:/data/config" \
  -v "$PWD/wiki:/data/wiki" \
  -v "$PWD/workspace:/data/workspace" \
  ghcr.io/lthoangg/openagentd
```

### Building from source (local Docker)

Use `docker-compose.local.yaml` to build the image from your working tree instead of pulling from GHCR:

```bash
cp .env.example .env              # if not already done
docker compose -f docker-compose.local.yaml up -d --build
```

## From source (development)

```bash
git clone https://github.com/lthoangg/openagentd.git
cd openagentd
cp .env.example .env              # add your API key(s)
uv sync                           # install Python deps
bun install --cwd web             # install frontend deps

make dev                              # backend (uvicorn :8000) + frontend (Vite :5173) with hot-reload
# API: http://localhost:8000   Web UI: http://localhost:5173
```

Requires [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh).

## First run

### Desktop app

Open the app, then go to **Settings → Providers**. Add an API-key provider or click **Connect** for OAuth providers such as GitHub Copilot or OpenAI Codex. After the first provider is saved, OpenAgentd installs the default agent team and skills automatically.

Existing OpenAgentd CLI users do not need to uninstall or migrate before installing the desktop app. The desktop sidecar uses the same XDG config and data paths as the CLI; see [`../../MIGRATION.md`](../../MIGRATION.md) for details.

### CLI / server

Run the setup wizard once:

```bash
openagentd init
```

`init` asks for a provider, model, API key when needed, and installs the default agent team and skills. Existing files are never overwritten, so re-running `init` is safe.

Config is written to `~/.config/openagentd/` (XDG standard). The desktop app and CLI share this same config directory. The database and logs go to `~/.local/share/openagentd/` and `~/.local/state/openagentd/`.

### Start the server

```bash
openagentd
```

The API and web UI start on a single port: http://localhost:4082. Database migrations run automatically.

### 3. First steps in the UI

- **Send a message** — the default lead agent (`openagentd`) is ready to chat. Start with something like "what can you do?" to explore its tools.
- **Switch agents** — click the agent name in the header to pick a different agent or spin up a team.
- **Workspace panel** — every file the agent reads, writes, or generates appears in the left panel. Click any file to preview or download it.
- **Command palette** — press `Ctrl+P` (or `Cmd+P` on macOS) to search sessions, agents, files, and actions.
- **Memory (Wiki)** — open the Wiki panel to view, edit, or delete anything the agent has remembered across sessions. The `USER.md` file at the top is always injected into every system prompt — edit it to give the agent standing context about you.

### 4. Customize your agent

Edit `~/.config/openagentd/agents/openagentd.md` to change the model, add tools, attach skills, or rewrite the system prompt. The agent picks up changes at the end of the next turn — no restart needed.

See [Configuration](configuration.md) for the full reference.

---

Database migrations run automatically on startup in production mode.

## Project layout (from source)

```
openagentd/
├── app/                    # FastAPI backend
│   ├── agent/              # Agent loop, hooks, providers, tools, teams
│   ├── api/                # Routes (thin — logic in services/)
│   ├── core/               # Config, DB, middleware, logging
│   ├── models/             # SQLModel DB schemas (chat)
│   └── services/           # Business logic, stream store, memory, dream
├── web/                    # React 19 frontend (Vite + Bun)
├── tests/                  # pytest test suite
├── seed/                   # Default config copied on first init (agents, skills, mcp.json)
└── documents/              # All documentation
```

## Next

- [CLI reference](cli.md) — every `openagentd` subcommand
- [Configuration](configuration.md) — env vars, agent YAML, providers, sandbox
- [Troubleshooting](troubleshooting.md) — common install/runtime issues
