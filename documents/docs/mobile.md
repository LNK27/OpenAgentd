---
title: Mobile app
description: Tauri mobile shell for connecting to remote OpenAgentd API servers.
status: draft
updated: 2026-05-28
---

# Mobile app

The mobile app is a Tauri shell that embeds the shared React Web UI and connects to a remote OpenAgentd API server. It is remote-backend-only: it does not bundle, start, or supervise the Python/FastAPI backend.

## Backend connection

Mobile uses the shared **Backend connection** UI:

- **Check** probes `<server>/api/health/live` and uses that server for the current WebView session.
- **Save** persists or renames a server for future use.
- Saved servers can be removed and show live status indicators.
- The built-in desktop sidecar row is hidden because mobile has no bundled backend.

For simulator development, `http://localhost:8000` usually reaches the Mac backend. Physical devices should use a LAN IP or HTTPS endpoint.

## Commands

```bash
cd mobile
make dev       # Tauri shell against Vite :5173
make ios-init  # generate iOS project files
make ios-dev   # run on simulator/device
make ios-build # build iOS app
```

Run a backend separately, for example:

```bash
make run
```
