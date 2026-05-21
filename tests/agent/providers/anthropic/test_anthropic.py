from __future__ import annotations

from pydantic import SecretStr

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.schemas.chat import (
    AssistantMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


def test_anthropic_provider_requires_api_key() -> None:
    try:
        AnthropicProvider(api_key="", model="claude-sonnet-4-6")
    except ValueError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_anthropic_provider_accepts_secret_str() -> None:
    provider = AnthropicProvider(
        api_key=SecretStr("sk-ant-test"),
        model="claude-sonnet-4-6",
    )

    assert provider.api_key == "sk-ant-test"
    assert provider.base_url == "https://api.anthropic.com"


def test_anthropic_payload_converts_system_tools_and_thinking() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-6",
        model_kwargs={"thinking_level": "low", "max_tokens": 4096},
    )

    payload = provider._payload(
        [
            SystemMessage(content="be concise"),
            HumanMessage(content="hi"),
            AssistantMessage(content=None, tool_calls=[]),
            ToolMessage(tool_call_id="toolu_1", content="ok"),
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup a value.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        provider._merged_kwargs(),
    )

    assert payload["system"] == "be concise"
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["thinking"]["budget_tokens"] == 1024
