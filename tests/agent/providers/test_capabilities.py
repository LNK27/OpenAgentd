"""Tests for the capabilities system.

Capabilities are resolved by longest-prefix match against
:data:`_PREFIX_FALLBACKS`. There are no per-model overrides and no
heuristics — see ``app/agent/providers/capabilities.py``.
"""

from __future__ import annotations

import pytest

from app.agent.providers.capabilities import (
    ModelCapabilities,
    ModelInputCapabilities,
    ModelOutputCapabilities,
    get_capabilities,
)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


class TestModelInputCapabilities:
    def test_defaults(self):
        caps = ModelInputCapabilities()
        assert caps.vision is False
        assert caps.document_text is True
        assert caps.audio is False
        assert caps.video is False

    def test_custom_values(self):
        caps = ModelInputCapabilities(
            vision=True, document_text=False, audio=True, video=True
        )
        assert caps.vision is True
        assert caps.document_text is False
        assert caps.audio is True
        assert caps.video is True

    def test_to_dict(self):
        caps = ModelInputCapabilities(vision=True, document_text=False)
        assert caps.to_dict() == {
            "vision": True,
            "document_text": False,
            "audio": False,
            "video": False,
        }

    def test_frozen(self):
        caps = ModelInputCapabilities()
        with pytest.raises(AttributeError):
            caps.vision = True  # type: ignore[misc]


class TestModelOutputCapabilities:
    def test_defaults(self):
        caps = ModelOutputCapabilities()
        assert caps.text is True
        assert caps.image is False
        assert caps.audio is False

    def test_to_dict(self):
        caps = ModelOutputCapabilities(text=True, image=True)
        assert caps.to_dict() == {"text": True, "image": True, "audio": False}


class TestModelCapabilities:
    def test_defaults(self):
        caps = ModelCapabilities()
        assert caps.input.vision is False
        assert caps.input.document_text is True
        assert caps.output.text is True

    def test_to_dict(self):
        caps = ModelCapabilities(input=ModelInputCapabilities(vision=True))
        d = caps.to_dict()
        assert d["input"]["vision"] is True
        assert d["output"]["text"] is True


# ─────────────────────────────────────────────────────────────────────────────
# get_capabilities — prefix matching
# ─────────────────────────────────────────────────────────────────────────────


class TestPrefixLookup:
    def test_none_returns_default(self):
        caps = get_capabilities(None)
        assert caps.input.vision is False
        assert caps.input.document_text is True

    def test_empty_string_returns_default(self):
        caps = get_capabilities("")
        assert caps.input.vision is False

    def test_unknown_provider_returns_default(self):
        caps = get_capabilities("unknown_provider:some-model")
        assert caps.input.vision is False
        assert caps.input.document_text is True

    @pytest.mark.parametrize(
        "model_id,expected_vision",
        [
            ("googlegenai:gemini-3.1-pro-preview", True),
            ("vertexai:gemini-3-flash", True),
            ("geminicli:gemini-2.5-pro", True),
            ("openai:gpt-5", True),
            ("openai:any-future-model", True),
            ("copilot:gpt-5.4", False),
            ("codex:gpt-5.5", False),
            ("xai:grok-4", True),
            ("zai:glm-5", False),
            ("deepseek:deepseek-v4-pro", False),
            ("openrouter:any-model", False),
            ("nvidia:meta/llama-3.1-8b-instruct", False),
            ("ollama:llama3", False),
            ("router9:claude-sonnet-4-6", True),
            ("cliproxy:gpt-5.5", True),
            ("bedrock:anthropic.claude-opus-4-7", False),
        ],
    )
    def test_provider_prefix_vision(self, model_id: str, expected_vision: bool):
        caps = get_capabilities(model_id)
        assert caps.input.vision is expected_vision, model_id

    def test_case_insensitive(self):
        lower = get_capabilities("openai:gpt-5")
        upper = get_capabilities("OPENAI:GPT-5")
        assert lower.input.vision == upper.input.vision

    def test_document_text_default_true(self):
        # All providers inherit document_text=True from the default.
        for model_id in ("openai:gpt-5", "deepseek:foo", "ollama:bar"):
            assert get_capabilities(model_id).input.document_text is True
