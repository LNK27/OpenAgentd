"""Tests for MemoryContextHook."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.memory_context import MemoryContextHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
)
from app.agent.state import AgentState, ModelRequest, RunContext
from app.services.memory import seed_memory


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "memory"
    monkeypatch.setattr(settings, "OPENAGENTD_WIKI_DIR", str(target))
    seed_memory()
    yield target


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state() -> AgentState:
    return AgentState(messages=[HumanMessage(content="hi")], system_prompt="Base.")


def _request(prompt: str = "Base.", user: str = "hi") -> ModelRequest:
    return ModelRequest(messages=(HumanMessage(content=user),), system_prompt=prompt)


async def _invoke(hook: MemoryContextHook, req: ModelRequest) -> str:
    received: list[str] = []

    async def handler(r: ModelRequest) -> AssistantMessage:
        received.append(r.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), req, handler)
    return received[0]


@pytest.mark.asyncio
async def test_no_memory_match_passes_through_unchanged():
    result = await _invoke(MemoryContextHook(), _request(user="unrelated query"))

    assert result == "Base."


@pytest.mark.asyncio
async def test_unrelated_query_does_not_inject_incidental_user_memory(
    _memory_dir: Path,
):
    (_memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct fact-based answers.", encoding="utf-8"
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="Explain Kubernetes pod scheduling.")
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_domain_specific_preference_query_does_not_inject_generic_preference(
    _memory_dir: Path,
):
    (_memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct fact-based answers.", encoding="utf-8"
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="What is Hoang's preferred Kubernetes scheduler plugin?"),
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_relevant_memory_is_injected(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct fact-based answers.", encoding="utf-8"
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    assert "## Relevant memory" in result
    assert "source=wiki:user" in result
    assert "direct fact-based" in result


@pytest.mark.asyncio
async def test_memory_search_failure_does_not_block_model_call(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.agent.hooks.memory_context.search_memory_files", _raise)

    result = await _invoke(MemoryContextHook(), _request(user="remember me"))

    assert result == "Base."


@pytest.mark.asyncio
async def test_memory_context_skips_followup_tool_call_iterations(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct fact-based answers.", encoding="utf-8"
    )
    req = ModelRequest(
        messages=(
            HumanMessage(content="How should you answer Hoang?"),
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="memory_search", arguments="{}"),
                    )
                ],
            ),
        ),
        system_prompt="Base.",
    )

    result = await _invoke(MemoryContextHook(), req)

    assert result == "Base."
