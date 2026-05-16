---
title: Desktop distribution
description: How OpenAgentd packages, ships, signs, and updates the native desktop app.
status: stable
updated: 2026-05-16
---

# Desktop distribution

The desktop app is a **Tauri v2 shell** wrapping the existing FastAPI
backend as a **Python sidecar**. Non-technical users download a single
installer (`.dmg`, `.exe`, or `.AppImage`) and double-click to run —
no Python install, no `uv tool install`, no terminal.

## Architecture

```
┌───────────────────────────── OpenAgentd.app / .exe / .AppImage ───┐
│                                                                    │
│  ┌─ Tauri Rust shell ─────────────────────────────────────────┐   │
│  │  • Native window + system tray                             │   │
│  │  • Process supervisor                                      │   │
│  │  • Auto-updater                                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│         │ spawns                              │ navigates           │
│         ▼                                     ▼                     │
│  ┌─ Python sidecar ──────────────┐  ┌─ WebView (system) ─────┐    │
│  │  python-build-standalone 3.14 │  │  http://127.0.0.1:<p>  │    │
│  │  + site-packages/             │  │  injects               │    │
│  │  + app/ (FastAPI)             │  │    __OAD_TOKEN__       │    │
│  │  bound to 127.0.0.1:<port>    │  │    (per-launch random) │    │
│  │  serves /api/* and SPA shell  │  └────────────────────────┘    │
│  └───────────────────────────────┘                                  │
│                                                                    │
└─────────────────────────────────────────────────────────────────────┘
```

The Tauri shell:

1. Locates the bundled CPython 3.14 inside the app bundle.
2. Spawns `python -m app.cli serve --handshake --generate-token --parent-pid <us>`.
3. Reads the JSON handshake line from stdout: `{"port":..., "token":..., "pid":..., "version":...}`.
4. Polls `http://127.0.0.1:<port>/api/health/live` for readiness.
5. Builds a WebView pointed at the backend, injecting the token as
   `window.__OAD_TOKEN__` via `initialization_script` *before* any page JS runs.
6. The bundled React UI's `installDesktopAuth()` patches `window.fetch`
   to attach `Authorization: Bearer <token>` to every same-origin
   `/api/*` request.
7. Installs native app-menu and tray-menu actions for opening the window,
   navigating to common routes, hiding to tray, and quitting cleanly.

The Python sidecar:

- Binds 127.0.0.1 on an OS-ephemeral port (`--port 0`) — no fixed
  port, so multiple instances can coexist and stale-lock conflicts
  are impossible.
- Generates a URL-safe random token, exposes it on the handshake line,
  and writes it into `OPENAGENTD_DESKTOP_TOKEN` for its middleware.
- Polls `--parent-pid` every 500 ms; if Tauri dies the backend exits
  cleanly (with a 5 s SIGTERM grace period before hard kill).
- On Windows, Tauri additionally puts the sidecar in a Job Object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` — the OS guarantees cleanup even
  if our own watch never fires.

## Security model

Without a token, anything else running on the user's machine could
reach the local API (read chat history, exfiltrate provider keys, run
agent tools). The token mitigates that.

| Aspect                                       | Behavior                                                                                                   |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Token lifetime                               | One launch only. Regenerated next start. Never persisted.                                                  |
| Token transport                              | `Authorization: Bearer …` for `fetch`/SSE; `?_token=…` for download links the browser can't header-stamp.  |
| Comparison                                   | `hmac.compare_digest` (constant-time).                                                                     |
| Bypassable routes                            | `/api/health/live`, `/api/health/ready`, `/metrics`, SPA shell (`/`, `/index.html`, `/assets/*`).          |
| Off-switch                                   | Unset `OPENAGENTD_DESKTOP_TOKEN` — the middleware becomes a no-op. CLI / Docker users keep open behaviour. |

See `app/core/desktop_auth.py` for the implementation and
`tests/core/test_desktop_auth.py` for the contract.

## Native menus and tray

The shell installs both native app menus and a system tray menu in `desktop/src-tauri/src/main.rs`.

| Surface | Actions |
|---------|---------|
| App menu / menu bar | **OpenAgentd**: About OpenAgentd, Show OpenAgentd, Settings, Telemetry, Quit OpenAgentd. **File**: Chat, Coding, Quit. **Edit**: Undo, Redo, Cut, Copy, Paste, Select All. **View**: Reload (`⌘/Ctrl+R`), Force Reload (`⌘/Ctrl+Shift+R`), Settings, Telemetry. **Window**: Minimize, Hide to Tray. |
| System tray | Status, Session, Show OpenAgentd, Chat, Coding, Settings, Telemetry, Reload Window, Quit OpenAgentd. |

The **Edit** submenu is required on macOS for native `⌘A` / `⌘C` / `⌘V` / `⌘X` / `⌘Z` to reach the webview's input fields — without it those shortcuts have no handler at the application level and the corresponding actions silently no-op inside the textarea. `Undo`/`Redo` are macOS-only and not registered on Windows/Linux; the other edit items work on all platforms.

The **About OpenAgentd** item opens the native About panel populated with the app icon, name, version (from `Cargo.toml` / `tauri.conf.json`), copyright, and a link to the project repository.

The **View → Reload** action (`⌘/Ctrl+R`) calls `window.location.reload()` on the main webview, respecting the HTTP cache. **Force Reload** (`⌘/Ctrl+Shift+R`) appends a cache-busting `__oad_reload` query param via `window.location.replace(...)` so the WebView refetches assets that may have been cached. The same action is mirrored on the tray as **Reload Window** for cases where the main window is hidden or wedged. Reload always brings the window to front before refreshing so the user sees the result.

Clicking the tray icon opens the tray menu (showing live status first) rather than summoning the main window. The window is summoned explicitly via the "Show OpenAgentd" entry. This matches macOS menu-bar app conventions where the icon is a status surface rather than a launcher.

Closing the main window hides it to the tray instead of stopping the backend. Selecting **Quit OpenAgentd** from the app menu or tray marks the app as quitting, exits Tauri, and lets the existing shutdown path terminate the Python sidecar cleanly.

The tray status starts at `Status: Starting`, changes to `Status: Running` once the backend is healthy, and changes to `Status: Error` if sidecar startup fails. In dev mode it reports `Status: Running (dev)`.

The tray **Session** line below status mirrors the user's active context with liveness taking priority over identity:

- `Working: <workspace-or-title>` (or just `Working…` if the session has no title yet) — the team is currently generating a response.
- `Coding: <workspace-name>` — a coding workspace is open but idle.
- `Chat: <session-title>` — a chat session has a server-named title and is idle.
- `No active session` — fallback when nothing is open.

The frontend pushes the label via the `set_tray_session` Tauri command (see `web/src/lib/tray.ts`) whenever the active mode/workspace/session-title or the team's working flag changes; the command silently truncates labels longer than 60 characters so the tray menu width stays sane.

## Window chrome

macOS uses the **Overlay** title-bar style (`tauri.conf.json` + `configure_window_chrome` in `main.rs`) — the OS keeps drawing the traffic-light buttons but the WebView extends edge-to-edge underneath. The React app reserves a 70 px left inset and provides the window-drag region itself.

The bundle includes `Info.plist` with `NSMicrophoneUsageDescription` so WebView microphone requests can show the native permission prompt. `entitlements.plist` grants `com.apple.security.device.audio-input` for signed builds. If macOS has already denied access, the frontend shows a native dialog and calls `open_macos_microphone_settings` to open **System Settings → Privacy & Security → Microphone**.

Windows and Linux keep their native title bars (`decorations: true`).

Implementation details (header, drag hook, traffic-light position tuning) live in [`web/chrome.md`](web/chrome.md).

## Bundle layout

### macOS (`OpenAgentd.app`)

```
OpenAgentd.app/
  Contents/
    MacOS/
      OpenAgentd                          ← Tauri executable
    Resources/
      sidecar/
        python/
          bin/python3
          lib/python3.14/
        site-packages/
          app/                            ← incl. _web_dist/
          fastapi/  pydantic/  …
      _up/                                ← Tauri updater artefacts
    Info.plist
```

User data (XDG-style, mapped to native dirs by Tauri at launch):

```
~/Library/Application Support/com.openagentd.desktop/   ← OPENAGENTD_DATA_DIR
~/Library/Application Support/com.openagentd.desktop/   ← OPENAGENTD_CONFIG_DIR (same root, but app/cli/paths.py keeps logical split)
~/Library/Caches/com.openagentd.desktop/                ← OPENAGENTD_CACHE_DIR
~/Library/Logs/com.openagentd.desktop/                  ← OPENAGENTD_STATE_DIR + sidecar stderr/stdout
```

### Windows (`OpenAgentd_<ver>_x64-setup.exe`)

```
%LOCALAPPDATA%\OpenAgentd\
  OpenAgentd.exe
  resources\
    sidecar\
      python\python.exe
      python\Lib\
      site-packages\
```

Per-user install (no UAC elevation, no Program Files) so auto-update
works without prompting.

### Linux (`OpenAgentd_<ver>_amd64.AppImage`, `.deb`)

```
/usr/lib/openagentd/sidecar/python/
/usr/lib/openagentd/sidecar/site-packages/
/usr/bin/OpenAgentd              ← Tauri executable, .deb only
```

AppImage is self-contained and the recommended Linux artefact.
`.deb` requires `libwebkit2gtk-4.1-0` and `libgtk-3-0` (declared in
the package manifest).

## Build pipeline

```bash
# Phase 1: web build + sidecar bundle
cd web && bun install --frozen-lockfile && bun run build && cd ..
cp -r web/dist/. app/_web_dist/

python3 scripts/build_sidecar.py \
  --root . \
  --out  desktop/sidecar-bundle \
  --python-version 3.14
```

The bundler:

1. Fetches python-build-standalone via `uv python install`.
2. `uv pip install --target` of `openagentd` (the local project) into
   `site-packages/`. Includes `markitdown[pdf,docx]` by default; HTML conversion
   uses markitdown core.
3. Strips `__pycache__`, `tests/`, `.pyc`, locale `.mo` files.
4. Runs a smoke test: starts `serve --handshake`, parses the handshake,
   SIGTERMs.

Current slim bundle size: **~470 MB** uncompressed (macOS arm64), including
`faster-whisper` + ONNX Runtime for built-in microphone voice input.
Optional `[audio,azure-doc-intel]` extras add ~80 MB.

```bash
# Phase 2: Tauri build
cd desktop && make icons      # one-time / on icon change
cd src-tauri && cargo tauri build
```

Output artefacts land in
`desktop/src-tauri/target/release/bundle/{dmg,msi,deb,appimage}/`.

## Release

A full release is **two workflows publishing into one GitHub tag** (`v<X.Y.Z>`):

| Workflow | Trigger | Cadence | Artefacts |
|---|---|---|---|
| `.github/workflows/release.yml` | `workflow_dispatch confirm=release` | ~90 s | `openagentd-<ver>-py3-none-any.whl`, `openagentd-<ver>.tar.gz`; publishes to PyPI. |
| `.github/workflows/release-desktop.yml` | `workflow_dispatch confirm=release-desktop` | ~20–25 min | `OpenAgentd_<ver>_aarch64.dmg`, `OpenAgentd_<ver>_x64_en-US.msi`, `OpenAgentd_<ver>_amd64.deb`, `latest.json`. |

Both workflows use a **create-or-upload** publish step (`gh release view "$TAG"` → `upload --clobber` if present, else `create`), so order doesn't matter for correctness. The runbook orders them PyPI-first so the canonical auto-generated release notes come from `release.yml`; the desktop matrix then appends its installers ~20 min later. See [`.opencode/commands/release.md`](../../.opencode/commands/release.md) for the operator runbook.

History — pre-1.0.9 releases used a split-tag scheme (`v<X.Y.Z>` for PyPI, `v<X.Y.Z>-desktop` for installers). That produced fragmented compare-links, duplicate release notes, and a confusing release listing. 1.0.9 consolidated everything under one tag; older `v*-desktop` tags remain on GitHub for archival but aren't created by the workflows anymore.

`release-desktop.yml` matrix:

1. macOS arm64 on `macos-26` (Tahoe — the host SDK matters for the title-bar geometry; see "Window chrome" above).
2. Windows x64 on `windows-latest`.
3. Linux x64 on `ubuntu-22.04`.

Each runner: `scripts/build_sidecar.py` → `cargo tauri build` → `gh release upload`. The `latest.json` updater manifest is produced after all three matrix legs succeed and uploaded to a rolling `latest-desktop` release that mirrors only the manifest (artefact URLs *inside* `latest.json` still point at the immutable `v<X.Y.Z>` release).

Signing happens when secrets are present:

- **macOS**: `APPLE_SIGNING_IDENTITY` + `APPLE_ID` + `APPLE_PASSWORD` + `APPLE_TEAM_ID` → notarized + stapled.
- **Windows**: `WINDOWS_CERTIFICATE` (when an Authenticode certificate is available) → signed installer.
- **Updater**: `TAURI_SIGNING_PRIVATE_KEY` + `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` → `.sig` files alongside artefacts.

When secrets are absent (today's default), the workflow conditionally **unsets** the Tauri signing env vars so `cargo tauri build` falls back to ad-hoc signing (`signingIdentity: "-"` in `tauri.conf.json`).

Tauri updater endpoint (in `tauri.conf.json`):

```
https://github.com/lthoangg/openagentd/releases/download/latest-desktop/latest.json
```

Companion publishers (run automatically off `workflow_run`):

- `.github/workflows/publish-homebrew.yml` — updates `lthoangg/homebrew-tap` `Formula/openagentd.rb` from the PyPI sdist after `release.yml` succeeds.
- `.github/workflows/publish-homebrew-cask.yml` — updates `lthoangg/homebrew-tap` `Casks/openagentd.rb` from the `.dmg` after `release-desktop.yml` succeeds. The resolver waits for a release with an `aarch64.dmg` asset attached, so the formula update and cask update don't race even though they're both triggered off the unified tag.

## Installation (unsigned builds)

Until paid code-signing certificates are wired into CI (Phase 3), the
release artefacts are **unsigned**. We ship a single installer entry
point per OS family:

| Platform        | Artefact                          | Install command                                  |
| --------------- | --------------------------------- | ------------------------------------------------ |
| macOS arm64     | `OpenAgentd-x.y.z.dmg`            | mount, then `/Volumes/OpenAgentd/install.sh --install` |
| Linux (any)     | `OpenAgentd-x.y.z.AppImage` (+ `.deb`, `.rpm`) | `./install.sh --install ./OpenAgentd-x.y.z.AppImage` |
| Windows x64     | `OpenAgentd-x.y.z-x64.msi`        | double-click; SmartScreen → *More info → Run anyway* |

The unified script lives at `desktop/scripts/install.sh`. It does
platform-specific work via an `uname -s` switch:

- **macOS branch** — strips `com.apple.quarantine`, ad-hoc codesigns
  the `.app` (`codesign --sign -`) with the bundle's
  `entitlements.plist`, verifies, optionally copies to
  `/Applications/`. The ad-hoc signature is what allows Gatekeeper
  to launch the bundle without an Apple Developer ID — without it,
  macOS reports the bundle as "damaged".
- **Linux branch** — `chmod +x`, copies to `~/.local/bin/openagentd`,
  writes a `.desktop` entry to `~/.local/share/applications/`,
  registers icons under `~/.local/share/icons/hicolor/`, and runs
  `update-desktop-database` / `gtk-update-icon-cache` if present.
  Detects `.deb` / `.rpm` arguments and defers to `dpkg` / `rpm`.

Windows uses **WiX MSI** rather than a custom script — `msiexec`
already handles registration, Start-Menu shortcut, and uninstall.
The MSI is unsigned, so first launch shows the SmartScreen
"unrecognized app" dialog; users click *More info → Run anyway* once.

User-facing copy lives in `desktop/scripts/INSTALL.md` and is
bundled inside every artefact via `tauri.conf.json` →
`bundle.resources`.

## Migration roadmap

| Phase  | Scope                                                                                       | Status         |
| ------ | ------------------------------------------------------------------------------------------- | -------------- |
| **0**  | Verify python-build-standalone 3.14 + heavy dep wheels on macOS / Windows / Linux           | ✅ done         |
| **1a** | Token auth middleware (`OPENAGENTD_DESKTOP_TOKEN`)                                          | ✅ done         |
| **1b** | Frontend `window.fetch` interceptor (`installDesktopAuth()`)                                | ✅ done         |
| **1c** | Slim core: `markitdown` heavy extras gated behind optional groups                           | ✅ done         |
| **1d** | Tauri v2 shell + sidecar supervisor + Job Object cleanup                                    | ✅ scaffolded   |
| **1e** | `scripts/build_sidecar.py` — python-build-standalone + `uv pip install --target` + smoke    | ✅ done         |
| **1f** | `.github/workflows/release-desktop.yml` — matrix build → signed artefacts → GitHub Release  | ✅ scaffolded   |
| **2**  | First-run provider setup inside the desktop shell (Settings → Providers, API keys + OAuth)  | ✅ done         |
| **2**  | Workspace picker / trust flow for coding mode                                               | ✅ done         |
| **2**  | `/api/diagnostics` endpoint + "Copy diagnostics" button                                     | ✅ done         |
| **3**  | macOS notarization, Windows Authenticode, Tauri updater public-key wiring                   | scaffold ready; needs certificates |
| **3**  | Update channels (stable / beta / nightly) → distinct `latest.json` URLs                     | partial         |

## What is intentionally NOT in scope

- **Intel macOS**: deferred. `macos-13` runners are deprecating;
  python-build-standalone arm64 builds are first-class. Intel users
  keep the `uv tool install openagentd` path until v2 ships universal2.
- **Removing `uv tool install`**: still supported, still recommended
  for developers and headless / server deployments. The desktop tier
  is **additional**, not a replacement.
- **Flatpak / Snap**: not for v1. AppImage covers ~90 % of Linux desktop
  installs without packaging complexity.
- **Frozen-Python compilation (Nuitka / PyInstaller)**: rejected.
  See `documents/techdebts/` for the analysis. Bundled CPython is
  more reliable for a fast-moving FastAPI/Pydantic codebase.

## Risk register

| Risk                                                                       | Mitigation                                                                                       |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Bundle size (~400 MB slim, ~750 MB with all extras)                        | Slim by default; on-demand feature packs in Phase 3.                                             |
| WebKitGTK version skew on Linux                                            | Officially support Ubuntu 22.04 LTS + 24.04 LTS; document fallback.                              |
| onnxruntime / pandas / lxml fail to build on Python 3.14                   | Wheels verified in Phase 0; CI re-checks on every release matrix run.                            |
| Backend process leaks after Tauri crash                                    | Parent-PID poll + Windows Job Object + 5 s SIGTERM grace.                                        |
| macOS Gatekeeper / Windows SmartScreen rejection of unsigned builds        | Signing wired into CI; pre-release builds clearly marked "unsigned" in the GitHub release notes. |
| Tauri auto-update private key compromise                                   | Re-key script (`scripts/generate_updater_keys.sh`) regenerates pair; old installs require manual re-download. |
| Concurrent Tauri+CLI desktop runs on the same machine                      | Dynamic ephemeral ports; XDG state dirs are user-global so DB writes are serialised by SQLite WAL. |
| Frontend assets duplicated in the wheel and re-bundled into the sidecar    | `make build-web` (or `cargo tauri build`'s `beforeBuildCommand`) syncs `web/dist → app/_web_dist`. `scripts/build_sidecar.py` fails fast if they drift. Ideally the sidecar would stop serving static assets entirely and let Tauri's webview load them from `frontendDist` — see future-work below. |
| Sidecar serves the web UI in parallel with Tauri's `frontendDist`          | Both paths point at functionally-identical assets, but only the sidecar's copy is what users actually see (the React app talks to `http://127.0.0.1:<port>/*` for everything, including HTML). Removing the duplication is a frontend refactor: make API calls relative to a configurable base URL, then drop `_web_dist` from the wheel for the desktop build. Saves ~50 MB. Tracked as future work. |
