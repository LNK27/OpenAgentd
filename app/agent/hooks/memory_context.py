"""MemoryContextHook — inject small query-relevant Memory v2 excerpts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.services.memory import MemorySearchResult
from app.services.memory import search_memory_files

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
    )

MAX_MEMORY_QUERY_CHARS = 500
MAX_MEMORY_CONTEXT_CHARS = 2_000
MEMORY_CONTEXT_TOP_K = 3
_AUTO_MEMORY_STOPWORDS = {
    "a",
    "an",
    "and",
    "do",
    "does",
    "how",
    "is",
    "me",
    "my",
    "of",
    "s",
    "should",
    "the",
    "to",
    "what",
    "you",
}
_AUTO_MEMORY_IDENTITY_TOKENS = {"hoang", "user"}
_AUTO_MEMORY_ALIASES = {
    "answer": "answer",
    "answers": "answer",
    "answered": "answer",
    "answering": "answer",
    "respond": "answer",
    "response": "answer",
    "responses": "answer",
    "prefer": "prefer",
    "preferred": "prefer",
    "prefers": "prefer",
    "preference": "prefer",
    "preferences": "prefer",
    "want": "want",
    "wants": "want",
}


class MemoryContextHook(BaseAgentHook):
    """Inject relevant Memory v2 snippets for the current user turn.

    This is intentionally conservative: it searches only from the latest user
    message, injects a small cited block, and never blocks the model call if
    memory search fails.
    """

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        query = self._latest_user_text(request)
        if not query:
            return await handler(request)

        try:
            results = search_memory_files(
                query,
                limit=MEMORY_CONTEXT_TOP_K,
                scope="compiled",
            )
        except Exception as exc:
            logger.warning("memory_context_search_failed error={}", exc)
            return await handler(request)

        results = self._filter_relevant_results(query, results)
        if not results:
            return await handler(request)

        lines = [
            "## Relevant memory",
            "",
            "Small, cited snippets that may help personalize this answer. Use only if relevant; do not overfit.",
        ]
        for result in results:
            location = f" path={result.path}" if result.path else ""
            lines.append(
                f"- source={result.source_ref}{location} score={result.score:.3f}: "
                f"{result.excerpt}"
            )
        block = "\n".join(lines)
        if len(block) > MAX_MEMORY_CONTEXT_CHARS:
            block = block[:MAX_MEMORY_CONTEXT_CHARS].rstrip() + "\n[truncated]"

        new_prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=new_prompt))

    def _filter_relevant_results(
        self, query: str, results: list[MemorySearchResult]
    ) -> list[MemorySearchResult]:
        query_tokens = self._meaningful_tokens(query)
        if not query_tokens:
            return []
        filtered: list[MemorySearchResult] = []
        for result in results:
            result_tokens = self._meaningful_tokens(result.excerpt)
            overlap = query_tokens & result_tokens
            query_only = query_tokens - result_tokens
            if not overlap:
                continue
            if len(overlap) == 1 and len(query_only) >= 2:
                continue
            filtered.append(result)
        return filtered

    def _meaningful_tokens(self, text: str) -> set[str]:
        import re

        tokens: set[str] = set()
        for raw in re.findall(r"[a-z0-9]+", text.lower()):
            token = _AUTO_MEMORY_ALIASES.get(raw, raw)
            if token in _AUTO_MEMORY_STOPWORDS:
                continue
            if token in _AUTO_MEMORY_IDENTITY_TOKENS:
                continue
            tokens.add(token)
        return tokens

    def _latest_user_text(self, request: "ModelRequest") -> str:
        for message in reversed(request.messages):
            if isinstance(message, HumanMessage):
                content = message.text_content() or ""
                return " ".join(content.split())[:MAX_MEMORY_QUERY_CHARS]
            if isinstance(message, AssistantMessage) and message.tool_calls:
                return ""
            if isinstance(message, ToolMessage):
                return ""
        return ""


default_memory_context_hook = MemoryContextHook()


__all__ = ["MemoryContextHook", "default_memory_context_hook"]
