"""Model capability detection.

Resolves input and output capabilities from the fully-qualified
``provider:model`` string stored in ``Agent.model_id``.

Lookup order:

1. Longest prefix match in :data:`_PREFIX_FALLBACKS`.
2. :data:`_DEFAULT`.

No per-model overrides and no name-substring heuristics: discovered
models trust the prefix, and edge cases (e.g. ``deepseek:foo-vision``)
fail at the provider boundary with a clear error. The benefit is a
maintenance-free registry — see ``documents/techdebts/model-capabilities-registry.md``
for the long-term direction if richer metadata becomes necessary.

Usage::

    from app.agent.providers.capabilities import get_capabilities

    caps = get_capabilities("googlegenai:gemini-3.1-pro-preview")
    caps.input.vision          # True — accepts image/png, image/jpeg, etc.
    caps.input.document_text   # True — markitdown for pdf/docx/txt/csv/json/md
    caps.output.text           # True — generates text responses
    caps.to_dict()             # {"input": {...}, "output": {...}}
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelInputCapabilities:
    """What the model can accept as input."""

    # Vision — accepts image/* files (png/jpg/gif/webp)
    vision: bool = False
    # Document text — markitdown conversion for pdf/docx/txt/csv/json/md
    document_text: bool = True
    # Audio input (not yet implemented — reserved for future use)
    audio: bool = False
    # Video input (not yet implemented — reserved for future use)
    video: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "vision": self.vision,
            "document_text": self.document_text,
            "audio": self.audio,
            "video": self.video,
        }


@dataclass(frozen=True)
class ModelOutputCapabilities:
    """What the model can generate as output."""

    # Text — generates text responses (almost all models)
    text: bool = True
    # Image generation (not yet implemented — reserved for future use)
    image: bool = False
    # Audio generation (not yet implemented — reserved for future use)
    audio: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "text": self.text,
            "image": self.image,
            "audio": self.audio,
        }


@dataclass(frozen=True)
class ModelCapabilities:
    """Composite input + output capabilities for a specific provider:model pair."""

    input: ModelInputCapabilities = ModelInputCapabilities()
    output: ModelOutputCapabilities = ModelOutputCapabilities()

    def to_dict(self) -> dict[str, dict[str, bool]]:
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict(),
        }


# ── Defaults & prefix fallbacks ──────────────────────────────────────────────

_DEFAULT = ModelCapabilities()

_PREFIX_FALLBACKS: list[tuple[str, ModelCapabilities]] = [
    # All Gemini providers: vision-capable
    ("googlegenai:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    ("vertexai:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    ("geminicli:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    # OpenAI generic: vision-capable (GPT-4o family and newer)
    ("openai:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    # Copilot generic: conservative — no vision
    ("copilot:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # Codex (ChatGPT subscription): conservative — no vision
    ("codex:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # xAI (Grok): vision on grok-4 family
    ("xai:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    # ZAI generic: conservative — no vision
    ("zai:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # DeepSeek: text-only
    ("deepseek:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # OpenRouter: too varied — conservative text-only
    ("openrouter:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # NVIDIA NIM: too varied — conservative text-only
    ("nvidia:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # Ollama: catalog spans text-only and vision; conservative default
    ("ollama:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
    # 9Router: aggregator proxy fronts vision-capable upstreams
    ("router9:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    # CLIProxyAPI: wraps Gemini/ChatGPT/Claude
    ("cliproxy:", ModelCapabilities(input=ModelInputCapabilities(vision=True))),
    # AWS Bedrock: too varied — conservative text-only default
    ("bedrock:", ModelCapabilities(input=ModelInputCapabilities(vision=False))),
]


# ── Public API ───────────────────────────────────────────────────────────────


def get_capabilities(model_id: str | None) -> ModelCapabilities:
    """Return capability set for a fully-qualified provider:model string.

    Lookup order:

    1. Longest prefix match in :data:`_PREFIX_FALLBACKS`.
    2. :data:`_DEFAULT`.

    Args:
        model_id: e.g. ``"googlegenai:gemini-3.1-pro-preview"``, ``"openai:gpt-5"``.
            ``None`` returns the defaults.
    """
    if not model_id:
        return _DEFAULT

    key = model_id.lower()

    best_prefix = ""
    best_caps: ModelCapabilities | None = None
    for prefix, caps in _PREFIX_FALLBACKS:
        if key.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_caps = caps

    if best_caps is not None:
        return best_caps

    return _DEFAULT
