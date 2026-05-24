#!/usr/bin/env python3
"""Build a relocatable Python sidecar bundle for the desktop shell.

Layout produced under ``<out>/``::

    sidecar-bundle/
      python/                ← python-build-standalone interpreter
        bin/python3          (POSIX)  /  python.exe (Windows)
        lib/python3.14/
      site-packages/         ← openagentd + dependencies
        app/                 ← our package (incl. _web_dist/)
        fastapi/
        pydantic/
        …

The Tauri shell runs a tiny bootstrap that adds
``sidecar-bundle/site-packages`` with ``site.addsitedir()`` so platform
``.pth`` files are processed, then runs
``app/cli/__main__.py serve --handshake --generate-token --parent-pid …``.

We deliberately do NOT use ``uv tool install`` — that produces an
isolated venv with absolute paths inside it, which won't survive being
copied into ``Contents/Resources/``. Instead we:

1. Fetch a python-build-standalone tarball for the target triple via
   ``uv python install --install-dir …``.
2. ``uv pip install --target <site-packages> --python <python-bin>``
   the local project + chosen extras.
3. Strip the ``site-packages/`` of caches, tests, docs.
4. Smoke-test the bundle by invoking ``serve --port 0 --handshake``.

Usage::

    python scripts/build_sidecar.py \\
        --root ./ --out ./desktop/sidecar-bundle \\
        --python-version 3.14 [--extras office,audio]

CI uses this same script on each runner (macos-14, windows-latest,
ubuntu-22.04). The output is consumed by the Tauri bundler via the
``bundle.resources`` entry in ``tauri.conf.json``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Patterns to strip from site-packages to shrink the bundle. Anything
# the runtime imports must survive — we intentionally do *not* drop
# `.pyi` files (some packages, e.g. pydantic-core, rely on metadata)
# or `__init__.py` files.
STRIP_DIRS = (
    "__pycache__",
    "tests",
    "test",
    ".dist-info/RECORD",  # pip metadata, not needed at runtime
)
STRIP_GLOBS = (
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pdb",  # MSVC debug symbols
    "**/*.dist-info/RECORD",
    # Heavy localization data we don't need:
    "**/locale/*.mo",
)


def detect_target_triple() -> str:
    """Return the python-build-standalone triple for the current host."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return "aarch64-apple-darwin" if machine in ("arm64", "aarch64") else "x86_64-apple-darwin"
    if system == "Windows":
        return "aarch64-pc-windows-msvc" if machine.startswith("arm") else "x86_64-pc-windows-msvc-shared"
    if system == "Linux":
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
        return "x86_64-unknown-linux-gnu"
    raise SystemExit(f"unsupported host: {system}/{machine}")


def run(cmd: list[str], **kwargs) -> None:
    print(">>", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def fetch_python(version: str, out: Path) -> Path:
    """Use uv to download python-build-standalone for ``version``.

    Returns the path to the python executable inside the install dir.
    """
    out.mkdir(parents=True, exist_ok=True)
    # ``uv python install --install-dir`` places one or more directories
    # under ``out``. As of uv 0.5+ the layout is:
    #
    #   <out>/cpython-<version>-<triple>/        ← real install root
    #     bin/python3.14                         (POSIX) or python.exe (Windows)
    #     lib/python3.14/
    #     ...
    #   <out>/cpython-<major>-<triple>           ← *symlink* to the versioned dir
    #
    # We must find the real directory, not the major-version symlink, or
    # ``shutil.move()`` later will move the symlink and leave us with a
    # broken pointer at the destination.
    run([
        "uv", "python", "install",
        "--install-dir", str(out),
        version,
    ])
    binary = _find_python_binary(out, version)
    if binary is None:
        listing = "\n  ".join(sorted(str(p) for p in out.iterdir()))
        raise SystemExit(
            f"no python binary found under {out}. Contents:\n  {listing}"
        )
    return binary


def _find_python_binary(root: Path, version: str) -> Path | None:
    """Locate the python interpreter inside a uv install root.

    Walks ``root`` looking for the canonical executable name(s) and
    returns the first hit that is a *real file* (not a broken symlink).
    """
    names: list[str]
    if os.name == "nt":
        names = ["python.exe"]
    else:
        # ``python3.X`` is the canonical name in python-build-standalone;
        # ``python3`` is a symlink to it. Prefer the versioned name so
        # the rest of the script doesn't follow a symlink it then has to
        # rewrite during normalisation.
        names = [f"python{version}", "python3"]
    for name in names:
        for candidate in root.rglob(name):
            # ``is_file()`` follows symlinks — we want both that the
            # symlink resolves *and* that the target exists. ``rglob``
            # already excludes broken symlinks on most platforms, but
            # be defensive.
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
    return None


def normalise_python_dir(install_root: Path, target: Path, python_bin: Path) -> Path:
    """Move uv's install tree to a flat ``target/`` directory.

    ``python_bin`` is the resolved (symlink-free) path to the interpreter
    inside ``install_root``. The Python install root is ``python_bin``'s
    grandparent (``bin/python`` → install root). We move *that* directory
    to ``target`` so the layout becomes::

        <target>/bin/python3.14
        <target>/lib/python3.14/
        ...

    Returns the new path of the python binary inside ``target``.
    """
    if os.name == "nt":
        # On Windows the binary lives directly in the install root.
        source = python_bin.parent
    else:
        # POSIX: <install_root>/bin/python3.X → parent.parent is the root.
        source = python_bin.parent.parent

    # Sanity check: the source must actually contain bin/ (or python.exe).
    if os.name == "nt":
        if not (source / "python.exe").is_file():
            raise SystemExit(
                f"resolved install root {source} missing python.exe"
            )
    else:
        if not (source / "bin").is_dir():
            raise SystemExit(
                f"resolved install root {source} missing bin/"
            )

    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # ``shutil.move`` on a directory works across filesystems by falling
    # back to copy + remove. The source might be inside a directory uv
    # also created symlinks into; that's fine — we only move *this*
    # directory, leaving siblings intact.
    shutil.move(str(source), str(target))

    # Compute the new binary path inside ``target`` and verify.
    if os.name == "nt":
        new_bin = target / "python.exe"
    else:
        new_bin = target / "bin" / python_bin.name
        if not new_bin.is_file():
            # Fall back to ``python3`` if the rglob picked the versioned
            # name on Linux but only ``python3`` exists at the target.
            alt = target / "bin" / "python3"
            if alt.is_file():
                new_bin = alt
    if not new_bin.is_file():
        raise SystemExit(
            f"normalisation moved tree but binary not at {new_bin}"
        )
    return new_bin


def install_packages(
    python_bin: Path, project_root: Path, site_packages: Path, extras: list[str]
) -> None:
    """Install the local openagentd project + extras into ``site_packages``."""
    site_packages.mkdir(parents=True, exist_ok=True)
    spec = "."
    if extras:
        spec = f".[{','.join(extras)}]"
    # uv pip install --target: PEP 668-safe, no virtualenv needed.
    run([
        "uv", "pip", "install",
        "--python", str(python_bin),
        "--target", str(site_packages),
        spec,
    ], cwd=project_root)


def strip_bundle(site_packages: Path) -> int:
    """Remove caches/tests/etc. from site-packages. Returns bytes saved."""
    removed = 0
    for pattern in STRIP_GLOBS:
        for p in site_packages.glob(pattern):
            try:
                if p.is_file():
                    removed += p.stat().st_size
                    p.unlink()
            except OSError:
                pass
    for name in ("__pycache__", "tests", "test"):
        for p in site_packages.rglob(name):
            if p.is_dir():
                try:
                    size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    removed += size
                except OSError:
                    pass
    return removed


def smoke_test(python_bin: Path, site_packages: Path) -> None:
    """Invoke the sidecar briefly to prove the bundle actually works.

    Stages:

    1. Spawn with the same env vars the desktop shell uses.
    2. Wait for the JSON handshake line on stdout (proves imports + bind).
    3. Hit ``/api/health/live`` *with* the generated token (proves
       middleware wiring + lifespan startup).
    4. Hit it *without* the token (proves 401 enforcement).
    5. SIGTERM and reap.

    Any failure here fails the build — we never want a broken bundle to
    leave CI.
    """
    import json
    import signal as _signal
    import time
    import urllib.error
    import urllib.request

    smoke_root = site_packages.parent / "_smoke"
    # PYTHONHOME must point at the python-build-standalone install root
    # — the directory containing ``Lib/`` (Windows) or ``lib/`` (POSIX).
    # On POSIX the interpreter lives at ``<root>/bin/python3.X`` so the
    # root is parent.parent. On Windows it lives at ``<root>/python.exe``
    # so the root is just parent.
    if os.name == "nt":
        python_home = python_bin.parent
    else:
        python_home = python_bin.parent.parent
    env = {
        **os.environ,
        "PYTHONHOME": str(python_home),
        "PYTHONPATH": str(site_packages),
        "PYTHONUNBUFFERED": "1",
        "APP_ENV": "production",
        # Keep test data isolated so the smoke run never touches the user's
        # real openagentd directories.
        "OPENAGENTD_DATA_DIR": str(smoke_root / "data"),
        "OPENAGENTD_CONFIG_DIR": str(smoke_root / "config"),
        "OPENAGENTD_STATE_DIR": str(smoke_root / "state"),
        "OPENAGENTD_CACHE_DIR": str(smoke_root / "cache"),
        "OPENAGENTD_WIKI_DIR": str(smoke_root / "wiki"),
        "OPENAGENTD_WORKSPACE_DIR": str(smoke_root / "workspace"),
    }

    # Use __main__.py path explicitly rather than ``-m app.cli`` so we
    # know *which* app.cli the interpreter finds — defends against a
    # vendored layout that buries app/ deeper later.
    cli_entry = site_packages / "app" / "cli" / "__main__.py"
    if not cli_entry.is_file():
        raise SystemExit(f"smoke test: missing CLI entry at {cli_entry}")

    bootstrap = (
        "import sys, runpy, site; "
        "_site = sys.argv.pop(1); "
        "_entry = sys.argv.pop(1); "
        "site.addsitedir(_site); "
        "sys.argv[0] = _entry; "
        "runpy.run_path(_entry, run_name='__main__')"
    )
    proc = subprocess.Popen(
        [str(python_bin), "-c", bootstrap, str(site_packages), str(cli_entry), "serve",
         "--host", "127.0.0.1", "--port", "0",
         "--handshake", "--generate-token"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True,
        # Cross-platform process group so the smoke test can hard-kill
        # the child (and any uvicorn worker it spawns) on timeout.
        start_new_session=(os.name != "nt"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,  # type: ignore[attr-defined]
    )

    # Read stdout from a background thread so the main thread can
    # enforce a real wall-clock timeout. ``subprocess.Popen.stdout`` is
    # buffered and blocking; without this scaffold, a child that goes
    # quiet hangs the smoke test indefinitely (observed on Windows GHA
    # runners).
    import queue as _queue
    import threading as _threading

    stdout_queue: "_queue.Queue[str | None]" = _queue.Queue()

    def _drain_stdout() -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            stdout_queue.put(line)
        stdout_queue.put(None)  # EOF sentinel

    reader = _threading.Thread(target=_drain_stdout, daemon=True)
    reader.start()

    payload: dict | None = None
    try:
        deadline = 60.0
        start = time.monotonic()
        while True:
            remaining = deadline - (time.monotonic() - start)
            if remaining <= 0:
                raise SystemExit("smoke test: handshake did not arrive in 60s")
            try:
                line = stdout_queue.get(timeout=remaining)
            except _queue.Empty:
                raise SystemExit("smoke test: handshake did not arrive in 60s")
            if line is None:
                err = proc.stderr.read() if proc.stderr else ""
                raise SystemExit(
                    f"smoke test: sidecar exited before handshake.\nstderr:\n{err[-4000:]}"
                )
            line = line.strip()
            if line.startswith("OPENAGENTD_HANDSHAKE "):
                payload = json.loads(line.split(" ", 1)[1])
                break

        assert payload is not None
        port = payload["port"]
        token = payload["token"]
        base = f"http://127.0.0.1:{port}"
        print(f"smoke test: handshake ok: port={port} version={payload['version']}")

        # ── /api/health/live without token → must 401 ──────────────────────
        try:
            urllib.request.urlopen(f"{base}/api/health/live")
            # /api/health/live is exempt — no auth required even when token set.
            # That's intentional: orchestrator probes must work.
            print("smoke test: health/live reachable without token (exempt — expected)")
        except urllib.error.HTTPError as e:
            raise SystemExit(
                f"smoke test: health/live unexpectedly returned {e.code}"
            ) from e

        # ── /api/team/status without token → must 401 ──────────────────────
        try:
            urllib.request.urlopen(f"{base}/api/team/status", timeout=5)
            raise SystemExit("smoke test: protected endpoint accepted request without token")
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise SystemExit(
                    f"smoke test: expected 401 without token, got {e.code}"
                ) from e
            print("smoke test: protected endpoint correctly rejects missing token")

        # ── /api/team/status with token → must succeed (2xx or 503 OK) ─────
        req = urllib.request.Request(
            f"{base}/api/team/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            print("smoke test: protected endpoint accepts bearer token")
        except urllib.error.HTTPError as e:
            # 4xx other than 401 is OK (e.g. 404 if route changed), 5xx
            # is not — that signals the request reached the app but the
            # app blew up.
            if e.code == 401:
                raise SystemExit(
                    "smoke test: protected endpoint rejected valid token"
                ) from e
            if 500 <= e.code < 600:
                raise SystemExit(
                    f"smoke test: protected endpoint returned {e.code}"
                ) from e
            print(f"smoke test: protected endpoint returned {e.code} (acceptable)")
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.send_signal(_signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        # Wipe the isolated smoke data dirs so we don't leak hundreds
        # of MB of throwaway state next to the bundle.
        shutil.rmtree(smoke_root, ignore_errors=True)


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def report_size(root: Path, label: str) -> None:
    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    print(f"  {label}: {human_bytes(total)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="Project root containing pyproject.toml.")
    ap.add_argument("--out", default="desktop/sidecar-bundle", help="Output bundle directory.")
    ap.add_argument("--python-version", default="3.14",
                    help="Major.minor Python version to bundle (default: 3.14).")
    ap.add_argument("--extras", default="",
                    help="Comma-separated optional-dep extras to install (e.g. audio,azure-doc-intel,full).")
    ap.add_argument("--no-smoke", action="store_true",
                    help="Skip the post-build smoke test (not recommended).")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()

    # ── Fail fast on stale frontend ─────────────────────────────────────
    # The wheel built by ``uv pip install .`` packages ``app/_web_dist/``
    # — *not* ``web/dist/``. If a developer runs ``bun run build`` but
    # forgets to sync ``app/_web_dist/``, the sidecar silently ships the
    # last-synced UI and the user sees stale code in the desktop app.
    # Catch it here rather than at runtime.
    web_dist = root / "web" / "dist" / "index.html"
    app_web_dist = root / "app" / "_web_dist" / "index.html"
    if not app_web_dist.is_file():
        raise SystemExit(
            f"error: {app_web_dist} is missing.\n"
            f"       Run ``make build-web`` first to build the web UI and copy it\n"
            f"       into app/_web_dist/."
        )
    if web_dist.is_file() and web_dist.stat().st_mtime > app_web_dist.stat().st_mtime + 1:
        raise SystemExit(
            f"error: {app_web_dist} is older than {web_dist}.\n"
            f"       The sidecar bundle would ship a stale UI. Run ``make build-web``\n"
            f"       to copy web/dist/ → app/_web_dist/ before building the sidecar."
        )

    if out.exists():
        print(f"removing existing {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    extras = [x.strip() for x in args.extras.split(",") if x.strip()]

    print(f"target python: {args.python_version}")
    print(f"target triple: {detect_target_triple()}")
    print(f"extras:        {extras or '(none — slim core)'}")
    print(f"output dir:    {out}")

    # ── 1. Fetch python-build-standalone ─────────────────────────────────
    install_root = out / "_python_install"
    uv_python_bin = fetch_python(args.python_version, install_root)
    python_target = out / "python"
    python_bin = normalise_python_dir(install_root, python_target, uv_python_bin)
    shutil.rmtree(install_root, ignore_errors=True)
    print(f"python binary: {python_bin}")

    # ── 2. Install openagentd + deps into site-packages ───────────────────
    site_packages = out / "site-packages"
    install_packages(python_bin, root, site_packages, extras)

    # ── 3. Strip caches/tests/etc. ──────────────────────────────────────
    saved = strip_bundle(site_packages)
    print(f"stripped: {human_bytes(saved)}")

    # ── 4. Smoke test ───────────────────────────────────────────────────
    if not args.no_smoke:
        smoke_test(python_bin, site_packages)

    # ── 5. Report ────────────────────────────────────────────────────────
    print("\n=== bundle summary ===")
    report_size(python_target, "python runtime")
    report_size(site_packages, "site-packages")
    report_size(out, "TOTAL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
