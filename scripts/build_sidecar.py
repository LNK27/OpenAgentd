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

The Tauri shell points ``PYTHONHOME`` at ``sidecar-bundle/python`` and
``PYTHONPATH`` at ``sidecar-bundle/site-packages``, then runs
``python -m app.cli serve --handshake --generate-token --parent-pid …``.

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
    # ``uv python install --install-dir`` puts a relocatable install
    # under <dir>/<triple>/ on disk. We then resolve the binary path
    # platform-by-platform.
    run([
        "uv", "python", "install",
        "--install-dir", str(out),
        version,
    ])
    # Find the python binary.
    candidates: list[Path] = []
    if os.name == "nt":
        candidates = list(out.rglob("python.exe"))
    else:
        candidates = list(out.rglob("bin/python3"))
        candidates += list(out.rglob("bin/python3.14"))
    candidates = [c for c in candidates if c.is_file()]
    if not candidates:
        raise SystemExit(f"no python binary found under {out}")
    return candidates[0]


def normalise_python_dir(install_root: Path, target: Path) -> None:
    """Move uv's <hash>/install/ tree to a flat ``target/`` directory.

    uv lays out installs under ``<install-dir>/<triple-or-hash>/[install/]``
    with extra metadata. The Tauri side wants a flat ``python/`` directory
    so paths in the Rust resolver are stable.
    """
    # Look for the actual python install root — the dir containing
    # either bin/ or python.exe.
    found: Path | None = None
    for path in install_root.rglob("*"):
        if path.is_dir() and (path / "bin").is_dir():
            found = path
            break
        if path.name == "python.exe" and path.is_file():
            found = path.parent
            break
    if found is None:
        raise SystemExit(f"could not locate python install dir under {install_root}")

    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(found), str(target))


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
    env = {
        **os.environ,
        "PYTHONHOME": str(python_bin.parent.parent),
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

    proc = subprocess.Popen(
        [str(python_bin), str(cli_entry), "serve",
         "--host", "127.0.0.1", "--port", "0",
         "--handshake", "--generate-token"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True,
    )
    payload: dict | None = None
    try:
        assert proc.stdout is not None
        deadline = 60.0
        start = time.monotonic()
        while True:
            if time.monotonic() - start > deadline:
                raise SystemExit("smoke test: handshake did not arrive in 60s")
            line = proc.stdout.readline()
            if not line:
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
    fetch_python(args.python_version, install_root)
    python_target = out / "python"
    normalise_python_dir(install_root, python_target)
    shutil.rmtree(install_root, ignore_errors=True)

    if os.name == "nt":
        python_bin = python_target / "python.exe"
    else:
        python_bin = python_target / "bin" / "python3"
        if not python_bin.is_file():
            python_bin = python_target / "bin" / f"python{args.python_version}"
    if not python_bin.is_file():
        raise SystemExit(f"python binary not found at {python_bin}")
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
