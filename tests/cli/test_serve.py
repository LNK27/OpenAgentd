"""Tests for app/cli/commands/serve.py — desktop-shell entry point.

These tests cover the *non-blocking* surface area: argument parsing,
the handshake JSON format, and the parent-death helpers. Actually
spawning uvicorn is left to integration testing (scripts/build_sidecar.py
runs a real smoke test at bundle time).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from types import SimpleNamespace

from app.cli.commands.serve import (
    _configure_desktop_token,
    _emit_handshake,
    _pid_alive,
    _server_port,
)
from app.cli.main import build_parser


class TestParserWiring:
    def test_serve_subcommand_exists(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        # Defaults: dynamic port, no handshake unless asked.
        assert args.port == 0
        assert args.handshake is False
        assert args.generate_token is False
        assert args.parent_pid is None

    def test_serve_accepts_all_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--handshake",
                "--generate-token",
                "--parent-pid",
                "12345",
            ]
        )
        assert args.host == "127.0.0.1"
        assert args.handshake is True
        assert args.generate_token is True
        assert args.parent_pid == 12345


class TestServerPort:
    def test_reads_uvicorn_bound_port(self):
        sock = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 54321))
        uvicorn_server = SimpleNamespace(servers=[SimpleNamespace(sockets=[sock])])

        assert _server_port(uvicorn_server, fallback=0) == 54321

    def test_falls_back_when_socket_unavailable(self):
        uvicorn_server = SimpleNamespace(servers=[])

        assert _server_port(uvicorn_server, fallback=8000) == 8000

    def test_ignores_non_tcp_socket_address(self):
        sock = SimpleNamespace(getsockname=lambda: "not-a-tcp-address")
        uvicorn_server = SimpleNamespace(servers=[SimpleNamespace(sockets=[sock])])

        assert _server_port(uvicorn_server, fallback=8000) == 8000


class TestHandshakeFormat:
    def test_handshake_is_single_json_line_with_prefix(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _emit_handshake(port=12345, token="tok", version="0.0.1")
        output = buf.getvalue()
        # Exactly one line.
        assert output.count("\n") == 1
        # Marker prefix the Tauri side greps for.
        assert output.startswith("OPENAGENTD_HANDSHAKE ")
        # Parsable JSON after the prefix.
        payload = json.loads(output.removeprefix("OPENAGENTD_HANDSHAKE ").strip())
        assert payload["port"] == 12345
        assert payload["token"] == "tok"
        assert payload["version"] == "0.0.1"
        assert payload["pid"] == os.getpid()

    def test_handshake_omits_token_when_none(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _emit_handshake(port=1, token=None, version="0")
        payload = json.loads(
            buf.getvalue().removeprefix("OPENAGENTD_HANDSHAKE ").strip()
        )
        assert "token" not in payload

    def test_handshake_file_env_var_writes_payload(self, monkeypatch, tmp_path):
        """When ``OPENAGENTD_HANDSHAKE_FILE`` is set, the JSON payload is
        also written to that path atomically (tmp + rename).

        The desktop sidecar on Windows uses this as a fallback channel
        because the anonymous-pipe + tokio overlapped-I/O combination has,
        on at least two user installs, failed to deliver the stdout
        handshake line.  The Python side must be cross-platform — the
        file is written whenever the env var is set, regardless of OS.
        """
        target = tmp_path / "handshake.json"
        monkeypatch.setenv("OPENAGENTD_HANDSHAKE_FILE", str(target))

        buf = io.StringIO()
        with redirect_stdout(buf):
            _emit_handshake(port=54321, token="tok", version="9.9.9")

        # Stdout still got the handshake line (primary channel).
        assert buf.getvalue().startswith("OPENAGENTD_HANDSHAKE ")

        # File got the same payload.
        assert target.exists()
        payload = json.loads(target.read_text())
        assert payload["port"] == 54321
        assert payload["token"] == "tok"
        assert payload["version"] == "9.9.9"
        assert payload["pid"] == os.getpid()

        # ``.tmp`` rename intermediate must be cleaned up.
        assert not (tmp_path / "handshake.json.tmp").exists()

    def test_handshake_no_file_env_var_skips_file(self, monkeypatch, tmp_path):
        """Without ``OPENAGENTD_HANDSHAKE_FILE``, no file is written.

        Guards against a regression that would create an unexpected file
        in the working directory on every desktop spawn on macOS/Linux.
        """
        monkeypatch.delenv("OPENAGENTD_HANDSHAKE_FILE", raising=False)
        cwd_before = set(tmp_path.iterdir())
        monkeypatch.chdir(tmp_path)

        buf = io.StringIO()
        with redirect_stdout(buf):
            _emit_handshake(port=1, token=None, version="0")

        assert buf.getvalue().startswith("OPENAGENTD_HANDSHAKE ")
        assert set(tmp_path.iterdir()) == cwd_before


class TestDesktopTokenConfig:
    def test_reuses_existing_desktop_token(self, monkeypatch):
        monkeypatch.setenv("OPENAGENTD_DESKTOP_TOKEN", "existing-token")

        assert _configure_desktop_token(False) == "existing-token"

    def test_empty_existing_desktop_token_is_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENAGENTD_DESKTOP_TOKEN", "")

        assert _configure_desktop_token(False) is None

    def test_generate_desktop_token_sets_env(self, monkeypatch):
        original_token = os.environ.get("OPENAGENTD_DESKTOP_TOKEN")
        monkeypatch.delenv("OPENAGENTD_DESKTOP_TOKEN", raising=False)

        try:
            token = _configure_desktop_token(True)

            assert token
            assert os.environ["OPENAGENTD_DESKTOP_TOKEN"] == token
        finally:
            if original_token is None:
                os.environ.pop("OPENAGENTD_DESKTOP_TOKEN", None)
            else:
                os.environ["OPENAGENTD_DESKTOP_TOKEN"] = original_token


class TestPidAlive:
    def test_current_process_is_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_unlikely_pid_is_dead(self):
        # Probabilistically not in use; if it is, the test is flaky but
        # not in a way that matters for this assertion's intent.
        assert _pid_alive(2_147_483_640) is False

    def test_live_external_child_is_alive_without_being_killed(self):
        """Regression test for the 1.22.5 Windows bug.

        On Windows, ``os.kill(pid, 0)`` is NOT a "probe if alive" call —
        CPython implements it as ``TerminateProcess(pid, 0)``. That meant
        the previous ``_pid_alive`` would silently kill the desktop sidecar's
        parent watcher target. This test spawns a real child, asserts
        ``_pid_alive`` returns True for it, and then verifies the child
        is still running afterwards.
        """
        # ``python -c "import time; time.sleep(30)"`` is portable and
        # avoids shell quirks on Windows ``cmd``.
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # Give the child a beat to actually be schedulable.
            time.sleep(0.1)
            assert _pid_alive(proc.pid) is True
            # The crucial regression assertion: the probe must not have
            # killed the child. ``poll()`` returns None while running.
            time.sleep(0.1)
            assert proc.poll() is None, (
                "_pid_alive killed the target process — this is the "
                "Windows-only bug fixed in 1.22.6"
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def test_exited_child_is_dead(self):
        """``_pid_alive`` must return False once the target has exited.

        On Windows this exercises the ``GetExitCodeProcess`` branch — a
        handle to an exited process is still openable (zombie-like state),
        but the exit code is no longer ``STILL_ACTIVE``.
        """
        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=5)
        # Small grace period for the OS to reflect the exit on Windows.
        time.sleep(0.1)
        assert _pid_alive(proc.pid) is False
