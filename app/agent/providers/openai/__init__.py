"""OpenAI Chat Completions provider package."""

from .openai import OpenAIProvider

OpenAICompatibleProvider = OpenAIProvider

__all__ = ["OpenAICompatibleProvider", "OpenAIProvider"]
