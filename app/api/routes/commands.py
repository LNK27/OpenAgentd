"""Slash-command discovery and rendering for the chat input picker."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas.commands import (
    CommandListResponse,
    CommandRenderRequest,
    CommandRenderResponse,
    CommandSummary,
)
from app.services.commands import discover_commands, render_command

router = APIRouter()


@router.get("")
async def list_commands() -> CommandListResponse:
    rows = [
        CommandSummary(name=cmd.name, description=cmd.description, source=cmd.source)
        for cmd in discover_commands().values()
    ]
    rows.sort(key=lambda r: r.name)
    return CommandListResponse(commands=rows)


@router.post("/{name:path}/render")
async def render(name: str, body: CommandRenderRequest) -> CommandRenderResponse:
    commands = discover_commands()
    cmd = commands.get(name)
    if cmd is None:
        raise HTTPException(status_code=404, detail=f"Command '{name}' not found.")
    return CommandRenderResponse(
        name=cmd.name, content=render_command(cmd, body.arguments)
    )
