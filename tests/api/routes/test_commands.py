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
def workspaces(tmp_path: Path):
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    return workspace_a, workspace_b


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
async def test_list_without_workspace_ignores_project_local_commands(client, roots):
    project_openagentd, _project_opencode, global_openagentd, _global_opencode = roots
    _write(project_openagentd / "run.md", "---\ndescription: Local run\n---\nrun")
    _write(global_openagentd / "review.md", "---\ndescription: Review\n---\nreview")

    res = await client.get("/api/commands")

    assert res.status_code == 200
    assert res.json() == {
        "commands": [
            {
                "name": "review",
                "description": "Review",
                "source": "global-openagentd",
            }
        ]
    }


@pytest.mark.asyncio
async def test_list_returns_discovered(client, roots):
    project_openagentd, _project_opencode, _global_openagentd, _global_opencode = roots
    _write(project_openagentd / "commit.md", COMMIT)
    _write(
        project_openagentd / "git" / "push.md",
        "---\ndescription: Push.\n---\nPush body.\n",
    )

    res = await client.get(
        "/api/commands", params={"workspace": str(project_openagentd.parents[1])}
    )

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
        "/api/commands/commit/render",
        params={"workspace": str(project_openagentd.parents[1])},
        json={"arguments": "fix bug"},
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
        "/api/commands/git/push/render",
        params={"workspace": str(project_openagentd.parents[1])},
        json={"arguments": "force"},
    )

    assert res.status_code == 200
    assert res.json()["content"] == "Do force."


@pytest.mark.asyncio
async def test_render_unknown_returns_404(client):
    res = await client.post("/api/commands/nope/render", json={"arguments": ""})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_builtin_init_mentions_subfolder_agents_md(client):
    res = await client.post("/api/commands/init/render", json={"arguments": ""})

    assert res.status_code == 200
    content = res.json()["content"]
    assert "repo root and in each meaningful subfolder" in content
    assert "subfolder files should only include" in content


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

    res = await client.get(
        "/api/commands", params={"workspace": str(project_openagentd.parents[1])}
    )

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

    res = await client.post(
        "/api/commands/review/render",
        params={"workspace": str(project_opencode.parents[1])},
        json={"arguments": ""},
    )

    assert res.status_code == 200
    assert res.json() == {"name": "review", "content": "project opencode"}


@pytest.mark.asyncio
async def test_workspace_local_commands_do_not_leak_between_projects(
    client, workspaces
):
    workspace_a, workspace_b = workspaces
    _write(
        workspace_a / ".openagentd" / "commands" / "run.md",
        "---\ndescription: Run project A\n---\nrun a",
    )

    res_a = await client.get("/api/commands", params={"workspace": str(workspace_a)})
    res_b = await client.get("/api/commands", params={"workspace": str(workspace_b)})

    assert res_a.status_code == 200
    assert res_b.status_code == 200
    assert [c["name"] for c in res_a.json()["commands"]] == ["run"]
    assert res_b.json() == {"commands": []}


@pytest.mark.asyncio
async def test_render_uses_workspace_local_command(client, workspaces):
    workspace_a, workspace_b = workspaces
    _write(
        workspace_a / ".openagentd" / "commands" / "run.md",
        "---\ndescription: Run project A\n---\nrun a",
    )

    res_a = await client.post(
        "/api/commands/run/render",
        params={"workspace": str(workspace_a)},
        json={"arguments": ""},
    )
    res_b = await client.post(
        "/api/commands/run/render",
        params={"workspace": str(workspace_b)},
        json={"arguments": ""},
    )

    assert res_a.status_code == 200
    assert res_a.json() == {"name": "run", "content": "run a"}
    assert res_b.status_code == 404


@pytest.mark.asyncio
async def test_global_commands_are_available_for_each_workspace(
    client, roots, workspaces
):
    _project_openagentd, _project_opencode, global_openagentd, _global_opencode = roots
    workspace_a, workspace_b = workspaces
    _write(
        global_openagentd / "review.md",
        "---\ndescription: Global review\n---\nreview",
    )

    res_a = await client.get("/api/commands", params={"workspace": str(workspace_a)})
    res_b = await client.get("/api/commands", params={"workspace": str(workspace_b)})

    assert res_a.status_code == 200
    assert res_b.status_code == 200
    assert (
        res_a.json()
        == res_b.json()
        == {
            "commands": [
                {
                    "name": "review",
                    "description": "Global review",
                    "source": "global-openagentd",
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_list_rejects_missing_workspace(client, tmp_path):
    res = await client.get(
        "/api/commands", params={"workspace": str(tmp_path / "missing")}
    )

    assert res.status_code == 422
