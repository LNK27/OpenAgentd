# Troubleshooting

Common install and runtime issues. Run `openagentd doctor` first — it surfaces most of these automatically.

## Desktop app (most users)

### macOS — `OpenAgentd.app` is damaged and can't be opened

Gatekeeper is blocking the unsigned app bundle. Use the Homebrew cask instead:

```bash
brew install --cask lthoangg/tap/openagentd
```

Or mount the DMG and run the bundled installer:

```bash
./install.sh
```

If you dragged the app to `/Applications`, re-run the installer against the installed bundle:

```bash
./install.sh /Applications/OpenAgentd.app --force
```

### Windows — SmartScreen `Windows protected your PC`

Click **More info** → **Run anyway** once.

### Linux — AppImage won't launch

Make it executable first:

```bash
chmod +x OpenAgentd_*_amd64.AppImage
```

### In-app updater stuck on `Checking...`

Go to **Settings → About → Updates**, click **Cancel**, then try again. If it still hangs, use `brew upgrade --cask openagentd` on macOS or reinstall from the latest release.

### Desktop notifications don't appear

Open **Settings → Notifications**, enable notifications, and send a test notification. Also check the OS permission at **System Settings → Notifications → OpenAgentd**.

### Voice input shows "unavailable" on Windows

Voice transcription bundles a native runtime (`onnxruntime` via `faster_whisper`). If its DLLs can't load, OpenAgentd disables voice instead of failing at startup and **Settings → Voice** reports the runtime as unavailable. The three common causes:

1. **Missing Microsoft Visual C++ Redistributable.** `onnxruntime` requires the 2015–2022 x64 redistributable. Install it from an elevated PowerShell:

   ```powershell
   winget install --id Microsoft.VCRedist.2015+.x64 -e
   ```

   Reboot, then restart OpenAgentd.

2. **Windows Defender or third-party AV quarantined a bundled DLL.** Add an exclusion for the install directory (default `C:\Program Files\OpenAgentd`) under **Windows Security → Virus & threat protection → Manage settings → Exclusions → Add an exclusion → Folder**, then reinstall to restore any missing files.

3. **CPU lacks AVX/AVX2.** `onnxruntime` builds for Windows require AVX2. Check from PowerShell:

   ```powershell
   Get-CimInstance Win32_Processor | Select-Object Name, Caption
   ```

   On unsupported CPUs, leave voice off; text-only usage is unaffected.

Voice continues to work end-to-end on macOS and Linux without any extra setup.

## CLI / server (developers)

These troubleshooting steps apply if you're running OpenAgentd as a CLI or server (`openagentd`). If you installed the desktop app, see the Desktop app section above.

## `command not found: openagentd` after pip install

Make sure your Python scripts directory is on `PATH`. Try `python -m app.cli` as a fallback, or install with `uv tool install openagentd` (which manages PATH for you).

## `command not found: uv`

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## `command not found: bun` (development only)

Install Bun:

```bash
curl -fsSL https://bun.sh/install | bash
```

Bun is only needed for development. Production installs (`pip install` / Docker) don't require it.

## Server starts but the web UI shows a blank page

- If running from source without `make build-web`, use `make dev` instead — it starts uvicorn (:8000) and the Vite dev server (:5173) together with hot-reload.
- If using `openagentd`, run `make build-web` first to bundle the frontend into the package.

## `GOOGLE_API_KEY not set` or similar provider errors

Copy `.env.example` to the correct location (see [Configuration](configuration.md)) and add your API key. At least one LLM provider key is required.

## Gemini `400 INVALID_ARGUMENT` — unknown field in function declarations

The Gemini API rejects JSON Schema fields it doesn't recognise (`discriminator`, `const`, `exclusiveMinimum`, `additionalProperties`, etc.) in tool schemas. `GeminiProviderBase._sanitize_schema()` strips these automatically — if you see this error it likely means a tool schema contains a new unsupported field. Add it to `_UNSUPPORTED_SCHEMA_KEYS` in `app/agent/providers/googlegenai/googlegenai.py`. See [Gemini schema sanitization](agent/tools.md#gemini-schema-sanitization) for the full list.

## SQLite `database is locked` errors

Usually means two server instances are running. Run `openagentd stop`, then `openagentd`.

## MCP stdio server fails with `ExceptionGroup` or `FileNotFoundError`

If an MCP server configured with stdio (e.g., using `npx` or `uvx`) fails to start:
- Make sure the command is installed and available in your terminal.
- The desktop app automatically resolves your terminal's `PATH` by querying your login shell. If you just installed the tool, click **Restart** on the MCP server in the settings UI to trigger a dynamic re-detection of your `PATH` without restarting the desktop app.

## Docker: `permission denied` on `/data`

The container runs as a non-root user. Make sure the volume mount is writable:

```bash
docker compose down -v && docker compose up -d
```

## Related

- [Install](install.md)
- [CLI reference](cli.md)
- [Configuration](configuration.md)
