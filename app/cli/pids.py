"""PID file helpers: write/read/find running openagentd processes."""

from __future__ import annotations

import os
import sys

from app.cli.paths import _pid_file


def _write_pids(pids: list[int]) -> None:
    pid_file = _pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("\n".join(str(p) for p in pids))


def _read_pids() -> list[int]:
    pid_file = _pid_file()
    if not pid_file.exists():
        return []
    try:
        return [int(line) for line in pid_file.read_text().splitlines() if line.strip()]
    except ValueError:
        return []


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _windows_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes

    # WinDLL exists only on Windows. getattr keeps `ty check` clean on Linux CI.
    windll = getattr(ctypes, "WinDLL", None)
    if windll is None:
        return False
    kernel32 = windll("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    still_active = 259

    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        wintypes.DWORD(pid),
    )
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _find_pids() -> list[int]:
    """Find running PIDs, filtered to those still alive."""
    pids = _read_pids()
    if pids and any(_pid_alive(p) for p in pids):
        return pids
    return []


def _clear_pids() -> None:
    _pid_file().unlink(missing_ok=True)
