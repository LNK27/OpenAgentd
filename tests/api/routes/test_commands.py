"""Tests for /api/commands HTTP routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.commands import router as commands_router


@pytest.fixture
def roots(tmp_path: Path, monkeypatch):
    """Isolate every command-discovery root inside tmp_path."""
    cwd = tmp_path / "project"
    cwd.mkdir()
    project_openagentd = cwd / ".openagentd" / "commands"
    project_opencode = cwd / ".opencode" / "commands"
    global_config = tmp_path / "config"
    global_openagentd = global_config / "commands"
    global_opencode = tmp_path / "home" / ".config" / "opencode" / "commands"

    from app.core import config as config_module
    from app.services import commands as commands_module

    monkeypatch.setattr(
        config_module.settings, "OPENAGENTD_CONFIG_DIR", str(global_config)
    )
    monkeypatch.setattr(
        commands_module.Path,
        "home",
        classmethod(lambda cls: tmp_path / "home"),
    )
    # Run the API as if launched from the project dir so the route's
    # implicit ``Path.cwd()`` finds the project-local commands root.
    monkeypatch.chdir(cwd)
    return project_openagentd, project_opencode, global_openagentd, global_opencode


@pytest.fixture
async def client(roots):
    app = FastAPI()
    app.include_router(commands_router, prefix="/api/commands")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


COMMIT = """\
---
description: Make a commit.
---
Body for $ARGUMENTS.
"""


@pytest.mark.asyncio
async def test_list_empty(client):
    res = await client.get("/api/commands")
    assert res.status_code == 200
    assert res.json() == {"commands": []}


@pytest.mark.asyncio
async def test_list_returns_discovered(client, roots):
    project_openagentd, _project_opencode, _global_openagentd, _global_opencode = roots
    _write(project_openagentd / "commit.md", COMMIT)
    _write(
        project_openagentd / "git" / "push.md",
        "---\ndescription: Push.\n---\nPush body.\n",
    )

    res = await client.get("/api/commands")

    assert res.status_code == 200
    names = [c["name"] for c in res.json()["commands"]]
    assert names == ["commit", "git/push"]  # sorted alphabetically
    commit = res.json()["commands"][0]
    assert commit["description"] == "Make a commit."
    assert commit["source"] == "project-openagentd"


@pytest.mark.asyncio
async def test_render_substitutes_arguments(client, roots):
    project_openagentd, _project_opencode, _global_openagentd, _global_opencode = roots
    _write(project_openagentd / "commit.md", COMMIT)

    res = await client.post(
        "/api/commands/commit/render", json={"arguments": "fix bug"}
    )

    assert res.status_code == 200
    assert res.json() == {"name": "commit", "content": "Body for fix bug."}


@pytest.mark.asyncio
async def test_render_nested_command(client, roots):
    project_openagentd, _project_opencode, _global_openagentd, _global_opencode = roots
    _write(
        project_openagentd / "git" / "push.md",
        "---\ndescription: x\n---\nDo $ARGUMENTS.\n",
    )

    res = await client.post(
        "/api/commands/git/push/render", json={"arguments": "force"}
    )

    assert res.status_code == 200
    assert res.json()["content"] == "Do force."


@pytest.mark.asyncio
async def test_render_unknown_returns_404(client):
    res = await client.post("/api/commands/nope/render", json={"arguments": ""})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_precedence_is_local_before_global_and_openagentd_before_opencode(
    client, roots
):
    project_openagentd, project_opencode, global_openagentd, global_opencode = roots
    _write(
        global_opencode / "deploy.md",
        "---\ndescription: global opencode\n---\nglobal opencode",
    )
    _write(
        global_openagentd / "deploy.md",
        "---\ndescription: global openagentd\n---\nglobal openagentd",
    )
    _write(
        project_opencode / "deploy.md",
        "---\ndescription: project opencode\n---\nproject opencode",
    )
    _write(
        project_openagentd / "deploy.md",
        "---\ndescription: project openagentd\n---\nproject openagentd",
    )

    res = await client.get("/api/commands")

    assert res.status_code == 200
    assert res.json()["commands"] == [
        {
            "name": "deploy",
            "description": "project openagentd",
            "source": "project-openagentd",
        }
    ]


@pytest.mark.asyncio
async def test_local_opencode_wins_over_global_openagentd(client, roots):
    _project_openagentd, project_opencode, global_openagentd, _global_opencode = roots
    _write(
        global_openagentd / "review.md",
        "---\ndescription: global openagentd\n---\nglobal openagentd",
    )
    _write(
        project_opencode / "review.md",
        "---\ndescription: project opencode\n---\nproject opencode",
    )

    res = await client.post("/api/commands/review/render", json={"arguments": ""})

    assert res.status_code == 200
    assert res.json() == {"name": "review", "content": "project opencode"}
