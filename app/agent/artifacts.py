"""Session-scoped artifact path helpers for agent-generated files."""

from __future__ import annotations

from pathlib import Path

from app.agent.sandbox import get_sandbox

SESSION_METADATA_DIR = ".openagentd"
SESSIONS_DIR = "sessions"
TOOL_RESULTS_DIR = ".tool_results"
SHELL_TOOL_DIR = "shell"
TODOS_FILENAME = ".todos.json"


def session_artifact_dir(session_id: str | None = None) -> Path:
    """Return the metadata directory for the active sandbox session.

    When *session_id* is omitted, the active sandbox session id is used. If no
    session id is available, the path falls back to ``{workspace}/.openagentd``.
    """
    sandbox = get_sandbox()
    return workspace_session_artifact_dir(
        sandbox.workspace_root, session_id or sandbox.session_id
    )


def session_artifact_path(name: str, session_id: str | None = None) -> Path:
    """Return a file/directory path below the session artifact directory."""
    return session_artifact_dir(session_id) / name


def todos_path(session_id: str | None = None) -> Path:
    """Return the current session todo store path."""
    return session_artifact_path(TODOS_FILENAME, session_id)


def tool_results_root(session_id: str | None = None) -> Path:
    """Return the current session tool-result root directory."""
    return session_artifact_path(TOOL_RESULTS_DIR, session_id)


def shell_output_dir(session_id: str | None = None) -> Path:
    """Return the current session shell-output spill directory."""
    return tool_results_root(session_id) / SHELL_TOOL_DIR


def tool_results_dir(agent_name: str, session_id: str | None = None) -> Path:
    """Return the current session tool-result offload directory for an agent."""
    return tool_results_root(session_id) / agent_name


def workspace_session_artifact_dir(
    workspace_root: Path, session_id: str | None
) -> Path:
    """Return a session artifact directory for an explicit workspace root."""
    path = workspace_root / SESSION_METADATA_DIR
    if session_id:
        path = path / SESSIONS_DIR / session_id
    return path
