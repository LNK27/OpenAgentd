"""Tests for the slash-command discovery + render service."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.commands import discover_commands, render_command


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def roots(tmp_path: Path, monkeypatch):
    """Redirect every command-discovery root into an isolated tmp tree.

    Returns ``(cwd, proj_oad, proj_oc, global_oad, global_oc)`` so tests
    can populate exactly the roots they care about.
    """
    cwd = tmp_path / "project"
    cwd.mkdir()
    proj_oad = cwd / ".openagentd" / "commands"
    proj_oc = cwd / ".opencode" / "commands"
    global_config = tmp_path / "config"
    global_oad = global_config / "commands"
    global_oc = tmp_path / "home" / ".config" / "opencode" / "commands"

    from app.core import config as config_module
    from app.services import commands as commands_module

    monkeypatch.setattr(
        config_module.settings, "OPENAGENTD_CONFIG_DIR", str(global_config)
    )
    # Pin Path.home() inside the service so the opencode-global root lands
    # under tmp_path instead of the real user home. Patching the module's
    # ``Path`` would be too coarse; the service only calls ``Path.home``.
    monkeypatch.setattr(
        commands_module.Path,
        "home",
        classmethod(lambda cls: tmp_path / "home"),
    )
    return cwd, proj_oad, proj_oc, global_oad, global_oc


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


VALID = """\
---
description: Make a commit.
---
Commit body.
"""

NO_FRONTMATTER = "Just a body, no metadata.\n"

WITH_ARGS = """\
---
description: Use args.
---
Hello $ARGUMENTS, welcome.
"""


# ── discover_commands ───────────────────────────────────────────────────────


def test_discover_returns_empty_when_no_roots(roots):
    cwd, *_ = roots
    assert discover_commands(cwd=cwd) == {}


def test_discover_finds_command_in_each_root(roots):
    cwd, proj_oad, proj_oc, global_oad, global_oc = roots
    _write(proj_oad / "a.md", VALID)
    _write(proj_oc / "b.md", VALID)
    _write(global_oad / "c.md", VALID)
    _write(global_oc / "d.md", VALID)

    result = discover_commands(cwd=cwd)

    assert set(result.keys()) == {"a", "b", "c", "d"}
    assert result["a"].source == "project-openagentd"
    assert result["b"].source == "project-opencode"
    assert result["c"].source == "global-openagentd"
    assert result["d"].source == "global-opencode"


def test_precedence_project_openagentd_wins_over_global(roots):
    cwd, proj_oad, proj_oc, global_oad, global_oc = roots
    _write(
        proj_oad / "commit.md",
        "---\ndescription: project-oad\n---\nproject-oad body\n",
    )
    _write(
        proj_oc / "commit.md",
        "---\ndescription: project-oc\n---\nproject-oc body\n",
    )
    _write(
        global_oad / "commit.md",
        "---\ndescription: global-oad\n---\nglobal-oad body\n",
    )
    _write(
        global_oc / "commit.md",
        "---\ndescription: global-oc\n---\nglobal-oc body\n",
    )

    result = discover_commands(cwd=cwd)

    assert result["commit"].source == "project-openagentd"
    assert result["commit"].description == "project-oad"
    assert "project-oad body" in result["commit"].body


def test_nested_folders_become_slashed_names(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "git" / "commit.md", VALID)
    _write(proj_oad / "git" / "push.md", VALID)
    _write(proj_oad / "review.md", VALID)

    result = discover_commands(cwd=cwd)

    assert set(result.keys()) == {"git/commit", "git/push", "review"}


def test_missing_frontmatter_yields_empty_description_and_full_body(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "raw.md", NO_FRONTMATTER)

    result = discover_commands(cwd=cwd)

    assert result["raw"].description == ""
    assert result["raw"].body == "Just a body, no metadata."


def test_non_dict_frontmatter_is_ignored_gracefully(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "weird.md", "---\n- just a list\n---\nbody\n")

    result = discover_commands(cwd=cwd)

    assert result["weird"].description == ""
    assert result["weird"].body == "body"


# ── render_command ──────────────────────────────────────────────────────────


def test_render_substitutes_arguments_placeholder(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "greet.md", WITH_ARGS)

    cmd = discover_commands(cwd=cwd)["greet"]

    assert render_command(cmd, "world") == "Hello world, welcome."


def test_render_appends_arguments_when_no_placeholder(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "commit.md", VALID)

    cmd = discover_commands(cwd=cwd)["commit"]

    rendered = render_command(cmd, "fix bug")
    assert rendered.startswith("Commit body.")
    assert rendered.endswith("fix bug")


def test_render_with_no_arguments_leaves_body_unchanged(roots):
    cwd, proj_oad, *_ = roots
    _write(proj_oad / "commit.md", VALID)

    cmd = discover_commands(cwd=cwd)["commit"]

    assert render_command(cmd, "") == "Commit body."


def test_render_substitutes_all_occurrences(roots):
    cwd, proj_oad, *_ = roots
    _write(
        proj_oad / "echo.md",
        "---\ndescription: x\n---\n$ARGUMENTS / $ARGUMENTS\n",
    )

    cmd = discover_commands(cwd=cwd)["echo"]

    assert render_command(cmd, "hi") == "hi / hi"
