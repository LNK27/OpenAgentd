from __future__ import annotations

import json

from app.agent.agent_loop.tool_executor import (
    _redact_tool_args_for_log,
    _redact_tool_result_for_log,
)
from app.agent.hooks.stream_publisher import _redact_tool_start_arguments


def test_hermes_skill_draft_args_are_redacted_for_logs() -> None:
    raw = json.dumps(
        {
            "task": "draft secret workflow",
            "context": "private operational context",
            "max_drafts": 2,
        }
    )

    redacted = _redact_tool_args_for_log("hermes_skill_draft", raw)

    assert "draft secret workflow" not in redacted
    assert "private operational context" not in redacted
    assert '"task": "<redacted>"' in redacted
    assert '"context": "<redacted>"' in redacted
    assert '"max_drafts": 2' in redacted


def test_hermes_skill_tool_result_preview_is_redacted_for_logs() -> None:
    result = '{"pending_id":"abc","body_preview":"private draft body"}'

    redacted = _redact_tool_result_for_log("hermes_skill_draft", result)

    assert "abc" not in redacted
    assert "private draft body" not in redacted
    assert redacted == "<redacted:hermes_skill_tool_result>"


def test_hermes_skill_draft_tool_start_stream_arguments_are_redacted() -> None:
    raw = json.dumps(
        {
            "task": "draft secret workflow",
            "context": "private operational context",
            "max_drafts": 2,
        }
    )

    redacted = _redact_tool_start_arguments("hermes_skill_draft", raw)

    assert redacted is not None
    assert "draft secret workflow" not in redacted
    assert "private operational context" not in redacted
    assert '"task": "<redacted>"' in redacted
    assert '"context": "<redacted>"' in redacted
    assert '"max_drafts": 2' in redacted
