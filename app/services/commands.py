"""Slash-command discovery and rendering.

Commands are markdown files with YAML frontmatter, reused from opencode's
format so users can share a single library between the two tools:

    ---
    description: One-line description shown in the picker
    ---

    Body becomes the user message. ``$ARGUMENTS`` (if present) is
    replaced with whatever the user typed after the command name; if
    the placeholder is absent, the arguments are appended on a new line.

Discovery walks four roots in precedence order — first hit wins on a
name collision, later sources are silently ignored:

    1. ``{cwd}/.openagentd/commands/``  (project, OpenAgentd-native)
    2. ``{cwd}/.opencode/commands/``    (project, opencode reuse)
    3. ``{OPENAGENTD_CONFIG_DIR}/commands/``     (global, OpenAgentd)
    4. ``~/.config/opencode/commands/`` (global, opencode reuse)

Nested folders are honoured: ``commands/git/commit.md`` registers as
``git/commit`` so users can group related commands. The forward slash
is preserved verbatim in the command id — the picker matches against it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import settings


@dataclass(frozen=True)
class Command:
    """A discovered slash command."""

    name: str  # e.g. "commit" or "git/commit"
    description: str
    body: str  # post-frontmatter markdown, untouched
    path: Path  # absolute path to the source .md file
    source: str  # one of: project-openagentd / project-opencode / global-openagentd / global-opencode


# ── Discovery roots ─────────────────────────────────────────────────────────


def _candidate_roots(cwd: Path | None = None) -> list[tuple[Path, str]]:
    """Ordered list of ``(root_dir, source_label)`` to search.

    Roots that don't exist are still returned — the caller filters them
    out — so the precedence rule is deterministic regardless of which
    sources happen to be present on disk.
    """
    cwd = cwd or Path.cwd()
    home = Path.home()
    config = Path(settings.OPENAGENTD_CONFIG_DIR)
    return [
        (cwd / ".openagentd" / "commands", "project-openagentd"),
        (cwd / ".opencode" / "commands", "project-opencode"),
        (config / "commands", "global-openagentd"),
        (home / ".config" / "opencode" / "commands", "global-opencode"),
    ]


# ── Parsing ─────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Mirrors ``app.agent.tools.builtin.skill._parse_frontmatter`` — kept
    private here to avoid a cross-package import that would pull the
    skill tool's settings into ``services``.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, match.group(2).strip()


def _iter_md(root: Path):
    """Yield ``(absolute_path, command_name)`` for every ``*.md`` under *root*.

    The command name is the path relative to *root* with the ``.md``
    suffix stripped — nested folders are preserved as ``a/b/c``.
    """
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).with_suffix("")
        # ``as_posix`` normalises separators on Windows so command ids
        # stay platform-independent.
        yield path, rel.as_posix()


# ── Public API ──────────────────────────────────────────────────────────────


def discover_commands(cwd: Path | None = None) -> dict[str, Command]:
    """Return ``{name: Command}`` for every command across the four roots.

    First-source wins on conflict. ``cwd`` is exposed for tests; production
    callers pass nothing and get ``Path.cwd()``.
    """
    commands: dict[str, Command] = {}
    for root, source in _candidate_roots(cwd):
        for path, name in _iter_md(root):
            if name in commands:
                continue  # earlier source wins
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            description = meta.get("description", "")
            if not isinstance(description, str):
                description = ""
            commands[name] = Command(
                name=name,
                description=description.strip(),
                body=body,
                path=path,
                source=source,
            )
    return commands


def render_command(command: Command, arguments: str = "") -> str:
    """Substitute ``$ARGUMENTS`` in *command.body*.

    If the placeholder is present, every occurrence is replaced. If it
    is absent and *arguments* is non-empty, the arguments are appended
    on a new line so the LLM still sees them. Empty arguments leave
    the body untouched.
    """
    args = arguments.strip()
    if "$ARGUMENTS" in command.body:
        return command.body.replace("$ARGUMENTS", args)
    if args:
        return f"{command.body}\n\n{args}"
    return command.body
