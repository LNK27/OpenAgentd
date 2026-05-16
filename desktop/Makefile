# Build the desktop app and its Python sidecar.
#
# Targets:
#   make sidecar        Build a slim Python sidecar bundle for the current OS/arch.
#   make sidecar-full   Same, but with [audio,azure-doc-intel] extras.
#   make icons          Regenerate .icns / .ico from icons/icon.png.
#   make dev            Tauri shell + Vite dev server, points at an external
#                       backend. You must run the backend in another terminal
#                       (``cd .. && make dev`` from the repo root).
#   make dev-bundled    Tauri shell with the *bundled* sidecar (requires
#                       ``make sidecar`` first). Use this to test the
#                       sidecar handshake / auth wiring end-to-end.
#   make build          Build a release desktop app.
#   make clean          Remove build artefacts.
#
# Dev-mode two-terminal flow (``make dev``):
#
#     terminal 1:   make dev          # repo root → FastAPI :8000 + Vite :5173
#                                     #   (the root Makefile runs both with
#                                     #    `trap 'kill 0' INT TERM EXIT`)
#     terminal 2:   cd desktop && make dev    # Tauri shell → loads :5173
#
# The Tauri shell skips its bundled-Python supervisor when
# ``OPENAGENTD_DEV_BACKEND_URL`` is set, so you get HMR on the frontend
# (via Vite), uvicorn reload on the backend, and quick Rust recompiles
# on the shell. Vite's HTTP proxy forwards ``/api/**`` and SSE streams
# to :8000 transparently.

.PHONY: sidecar sidecar-full icons dev dev-bundled build clean

ROOT       := $(abspath ..)
BUNDLE     := sidecar-bundle
PYVER      := 3.14
EXTRAS     ?=                       # set to e.g. "audio,azure-doc-intel,full"
DEV_URL    ?= http://localhost:5173

sidecar:
	@python3 ../scripts/build_sidecar.py \
		--root "$(ROOT)" \
		--out  "$(BUNDLE)" \
		--python-version "$(PYVER)" \
		$(if $(EXTRAS),--extras "$(EXTRAS)",)

sidecar-full:
	@$(MAKE) sidecar EXTRAS="audio,azure-doc-intel"

icons:
	cd src-tauri && cargo tauri icon icons/icon.png

# Dev: point the shell at an externally-managed backend (Vite dev server,
# which proxies /api to FastAPI on :8000). The shell skips sidecar spawn.
# ``beforeDevCommand`` is intentionally absent from tauri.conf.json so
# ``cargo tauri dev`` does NOT try to start its own Vite — we rely on the
# repo-root ``make dev`` to manage Vite + FastAPI together.
#
# ``-c tauri.dev.conf.json`` overrides the bundle identifier + product
# name so the dev build coexists with a Homebrew-cask-installed prod
# build (they get separate Dock icons, tray entries, and log dirs).
# Without this, macOS routes ``open -a OpenAgentd`` to whichever
# instance is already running, masking which app you're testing.
dev:
	@echo "→ Tauri dev shell. Make sure backend (port 8000) + Vite ($(DEV_URL)) are running."
	cd src-tauri && OPENAGENTD_DEV_BACKEND_URL="$(DEV_URL)" cargo tauri dev -c tauri.dev.conf.json

# Dev with the bundled CPython sidecar — the closest thing to ``make build``
# without producing a .dmg. Useful for testing handshake, token injection,
# Job-Object cleanup, and the ``app.cli serve`` entry path.
dev-bundled: sidecar
	cd src-tauri && cargo tauri dev -c tauri.dev.conf.json

build:
	cd src-tauri && cargo tauri build

clean:
	rm -rf "$(BUNDLE)" src-tauri/target
