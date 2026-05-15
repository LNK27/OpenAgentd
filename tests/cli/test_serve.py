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
from contextlib import redirect_stdout

from app.cli.commands.serve import (
    _bind_socket,
    _emit_handshake,
    _pid_alive,
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


class TestBindSocket:
    def test_port_zero_picks_ephemeral(self):
        sock = _bind_socket("127.0.0.1", 0)
        try:
            host, port = sock.getsockname()[:2]
            assert host == "127.0.0.1"
            assert 1024 < port < 65536
        finally:
            sock.close()

    def test_inheritable_flag_set(self):
        sock = _bind_socket("127.0.0.1", 0)
        try:
            assert sock.get_inheritable() is True
        finally:
            sock.close()


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


class TestPidAlive:
    def test_current_process_is_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_unlikely_pid_is_dead(self):
        # Probabilistically not in use; if it is, the test is flaky but
        # not in a way that matters for this assertion's intent.
        assert _pid_alive(2_147_483_640) is False
