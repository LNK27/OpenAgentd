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

## Icons

The mobile shell keeps `src-tauri/icons/icon.png` as the source icon. Generated icon outputs are ignored; regenerate them when the source changes:

```bash
cd mobile/src-tauri && cargo tauri icon icons/icon.png
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

For a physical iPhone, expose the dev servers on the LAN first:

```bash
cd ../web && bun dev --host 0.0.0.0
cd .. && uv run uvicorn app.server:app --host 0.0.0.0 --port 8000
```

Then run the iOS app:

```bash
make ios-dev-device <device-name>
```

For example, if `cargo tauri ios dev` detects a device named `OfficePhone`, run:

```bash
make ios-dev-device "OfficePhone"
```

If the generated Xcode project gets stale after changing signing or identifiers, clean and regenerate it:

```bash
make ios-clean
make ios-init
```

Build:

```bash
make ios-build
```

Use **Backend connection** in the app to save/check a remote server. Simulator builds can usually reach the Mac with `http://localhost:8000`; physical devices normally need a LAN IP or HTTPS endpoint.

For local developer builds, set a unique iOS bundle identifier in `src-tauri/tauri.conf.json` if `com.openagentd.mobile` is already registered to another Apple developer team.
