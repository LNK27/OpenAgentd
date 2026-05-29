# OpenAgentd mobile

Remote-backend-only Tauri mobile shell for OpenAgentd.

The mobile app embeds the shared React Web UI from `../web/dist` and connects to an existing OpenAgentd API server. It does not bundle or start the Python/FastAPI backend.

## Local development

Run the backend and Web UI from the repo root or separate directories:

```bash
make run          # backend API on :8000
cd web && make dev # Vite Web UI on :5173
```

Then run the mobile shell:

```bash
cd mobile
make dev
```

## iOS

Initialize iOS project files once:

```bash
cd mobile
make ios-init
```

Run on simulator/device:

```bash
make ios-dev
```

Build:

```bash
make ios-build
```

Use **Backend connection** in the app to save/check a remote server. Simulator builds can usually reach the Mac with `http://localhost:8000`; physical devices normally need a LAN IP or HTTPS endpoint.
