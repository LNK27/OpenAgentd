"""``openagentd`` (default) — launch the server in the background.

Single detached uvicorn process serving the bundled web UI from
``app/_web_dist/``; stdout/stderr redirected to the server log so the user
gets their shell back.
"""

from __future__ import annotations

import argparse
import os
import subprocess

from app.cli.firstrun import ensure_initialised
from app.cli.paths import _ROOT, _server_log
from app.cli.pids import _find_pids, _write_pids
from app.cli.server import _has_bundled_web, _server_cmd
from app.cli.ui import _bold, _dim, _print_banner, _yellow


_API_PORT = 4082


def _resolve_port(port: int | None) -> int:
    """Pick the API port when the user didn't pass ``--port`` explicitly."""
    return _API_PORT if port is None else port


def cmd_start(args: argparse.Namespace) -> None:
    args.port = _resolve_port(args.port)

    # Bail early if a server is already running — no point prompting the
    # user for init questions only to refuse to start. ``_find_pids`` only
    # returns when at least one PID is still alive.
    if _find_pids():
        print(f"  {_yellow('already running')}  (run {_bold('openagentd stop')} first)")
        return

    # First-run guard: if .env or agents are missing, run init interactively
    # before going any further. Headline UX is `openagentd` → working server.
    ensure_initialised()

    srv_log = _server_log()

    # Single uvicorn process (web UI bundled). FastAPI serves the pre-built
    # web/dist/ assets directly. No bun, no Vite, no separate web process.
    if not _has_bundled_web():
        print(
            f"  {_yellow('warning:')} No bundled web UI found. "
            f"API will work but no web UI will be served."
        )
        print(f"  {_dim('Build it:')}  make build-web")
        print()

    _print_banner(host=args.host, port=args.port)

    srv_log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "APP_ENV": "production"}

    with open(srv_log, "a") as srv_f:
        server = subprocess.Popen(
            _server_cmd(host=args.host, port=args.port),
            cwd=_ROOT,
            env=env,
            stdout=srv_f,
            stderr=srv_f,
            start_new_session=True,
        )

    _write_pids([server.pid])
    print(f"  {_dim('Logs:')}  {srv_log}")
    print(f"  {_dim('Stop:')}  {_bold('openagentd stop')}")
    print()
