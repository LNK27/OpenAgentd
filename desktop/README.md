# OpenAgentd Desktop (Tauri v2)

Native desktop shell for OpenAgentd. Spawns the Python backend as a
sidecar, points an embedded webview at it, and ships an auto-update +
signing pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  OpenAgentd.app  (Tauri Rust)                           │
│  ┌────────────────────────┐  ┌──────────────────────┐   │
│  │  WebView (system)      │  │  Sidecar supervisor  │   │
│  │  http://127.0.0.1:<p>  │  │  python ... serve    │   │
│  │  injects __OAD_TOKEN__ │──┤  --handshake         │   │
│  └────────────────────────┘  │  --generate-token    │   │
│                              │  --parent-pid <pid>  │   │
│                              └──────────┬───────────┘   │
└─────────────────────────────────────────┼───────────────┘
                                          │
                              ┌───────────▼─────────────┐
                              │  python-build-standalone │
                              │  + site-packages         │
                              │  + app/ (FastAPI)        │
                              │  + app/_web_dist/        │
                              └──────────────────────────┘
```

The Python sidecar:

1. Binds 127.0.0.1 on an OS-ephemeral port.
2. Generates a random URL-safe token.
3. Emits one JSON line on stdout: `OPENAGENTD_HANDSHAKE {"port":..., "token":..., "pid":...}`.
4. Then proceeds to start uvicorn normally.
5. Watches the Tauri PID; exits if the shell crashes.

The Tauri shell:

1. Locates the bundled Python runtime in `Contents/Resources/python/` (macOS),
   `resources\python\` (Windows), or `usr/lib/openagentd/python/` (Linux).
2. Spawns the sidecar with `--handshake --generate-token --parent-pid <our pid>`.
3. Reads stdout until the handshake line; extracts `{port, token}`.
4. Polls `http://127.0.0.1:<port>/api/health/live` until it returns 200.
5. Installs an `initialization_script` that sets `window.__OAD_TOKEN__ = "..."`.
6. Navigates the webview to `http://127.0.0.1:<port>/`.
7. On window-close: SIGTERM the sidecar; force-kill after 5s.

## Development

```sh
# Once: install Rust + Tauri CLI
rustup default stable
cargo install tauri-cli --version "^2.0" --locked

# Build the web UI first
cd web && bun install && bun run build && cd ..

# Build a slim Python sidecar bundle (uses uv + python-build-standalone)
make -C desktop sidecar

# Run the desktop shell in dev mode (prefer ``make dev`` from this
# directory so the dev override picks up — see ``Makefile``).
cd desktop && make dev
```

## Packaging

See [`../documents/docs/desktop.md`](../documents/docs/desktop.md) for the
full release pipeline (matrix builds, signing, notarization, updater).
