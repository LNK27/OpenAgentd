"""Skill CRUD: writes ``{SKILLS_DIR}/{name}/SKILL.md`` and invalidates the cache."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.skills import (
    SkillDeleteResponse,
    SkillDetail,
    SkillListResponse,
    SkillSummary,
    SkillWriteRequest,
)
from app.services import agent_fs, team_manager
from app.services.agent_fs import (
    AgentFsConflictError,
    AgentFsNotFoundError,
    AgentFsPathError,
)

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _builtin_skill_names() -> set[str]:
    root = Path(__file__).resolve().parents[2] / "agent" / "builtin_skills"
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}


def _parse_skill(name: str, content: str) -> tuple[str, str | None]:
    """Return ``(description, error)`` from a SKILL.md body."""
    from app.agent.tools.builtin.skill import _parse_frontmatter

    try:
        meta, _ = _parse_frontmatter(content)
    except Exception as exc:
        return "", f"Invalid frontmatter: {exc}"

    if not isinstance(meta, dict):
        return "", "Frontmatter must be a YAML mapping."

    desc = meta.get("description", "")
    if not isinstance(desc, str):
        return "", "'description' must be a string."
    frontmatter_name = meta.get("name", name)
    if frontmatter_name != name:
        return desc, (
            f"Frontmatter name '{frontmatter_name}' does not match directory "
            f"name '{name}'."
        )
    return desc.strip(), None


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_skills() -> SkillListResponse:
    builtin_names = _builtin_skill_names()
    rows: list[SkillSummary] = []
    for name in agent_fs.list_skills():
        try:
            record = agent_fs.read_skill(name)
        except Exception as exc:
            rows.append(
                SkillSummary(
                    name=name,
                    valid=False,
                    error=str(exc),
                    built_in=name in builtin_names,
                )
            )
            continue
        desc, err = _parse_skill(name, record.content)
        rows.append(
            SkillSummary(
                name=name,
                description=desc,
                valid=err is None,
                error=err,
                built_in=name in builtin_names,
            )
        )
    return SkillListResponse(skills=rows)


@router.get("/{name}")
async def get_skill(name: str) -> SkillDetail:
    try:
        record = agent_fs.read_skill(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    desc, err = _parse_skill(name, record.content)
    return SkillDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        description=desc,
        error=err,
        built_in=name in _builtin_skill_names(),
    )


@router.post("", status_code=201)
async def create_skill(body: SkillWriteRequest) -> SkillDetail:
    desc, err = _parse_skill(body.name, body.content)
    if err is not None:
        raise HTTPException(status_code=422, detail=err)

    try:
        record = agent_fs.write_skill(body.name, body.content, create=True)
    except AgentFsConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_manager.invalidate_skill_cache()
    return SkillDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        description=desc,
    )


@router.put("/{name}")
async def update_skill(name: str, body: SkillWriteRequest) -> SkillDetail:
    if body.name != name:
        raise HTTPException(
            status_code=422,
            detail=f"URL name '{name}' does not match body name '{body.name}'.",
        )
    desc, err = _parse_skill(name, body.content)
    if err is not None:
        raise HTTPException(status_code=422, detail=err)

    try:
        record = agent_fs.write_skill(name, body.content, create=False)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not (agent_fs.skills_dir() / name / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")

    team_manager.invalidate_skill_cache()
    return SkillDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        description=desc,
    )


@router.delete("/{name}")
async def delete_skill(name: str) -> SkillDeleteResponse:
    if name in _builtin_skill_names():
        raise HTTPException(
            status_code=403, detail=f"Built-in skill '{name}' cannot be deleted."
        )
    try:
        agent_fs.delete_skill(name)
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_manager.invalidate_skill_cache()
    return SkillDeleteResponse(name=name)
