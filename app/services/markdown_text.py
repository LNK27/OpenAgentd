"""Shared Markdown/frontmatter and tokenization helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import yaml


class VaultFrontmatterParseError(ValueError):
    """Raised when leading YAML frontmatter cannot be parsed safely."""


@dataclass(frozen=True)
class ParsedVaultNote:
    """Parsed Markdown note preserving body text exactly."""

    metadata: dict[str, Any]
    body: str
    had_frontmatter: bool


@dataclass(frozen=True)
class TokenSets:
    """Exact and folded token sets used by keyword scoring."""

    exact: set[str]
    folded: set[str]


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_TOKEN_SPLIT_RE = re.compile(r"[^\w]+|_+|-+")
_HEADING_MARKERS_RE = re.compile(r"^\s{0,3}(#{1,6}\s*|>\s*|[-*+]\s+)", re.MULTILINE)
_MARKDOWN_INLINE_RE = re.compile(r"[*_`]+")


def fold_vietnamese(text: str) -> str:
    """Return a no-diacritic folded form, including Vietnamese đ/Đ."""
    folded = text.replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", folded)
    return "".join(char for char in nfd if not unicodedata.combining(char))


def get_ordered_exact_tokens(text: str) -> list[str]:
    """Tokenize text with Unicode word support while treating _ and - as separators."""
    normalized = unicodedata.normalize("NFC", text.lower())
    tokens = [token for token in _TOKEN_SPLIT_RE.split(normalized) if len(token) >= 2]
    return list(dict.fromkeys(tokens))


def get_token_sets(text: str) -> TokenSets:
    """Return exact and folded token sets for search scoring."""
    exact_tokens = get_ordered_exact_tokens(text)
    folded_tokens = [
        folded
        for token in exact_tokens
        if len(folded := fold_vietnamese(token).lower()) >= 2
    ]
    return TokenSets(exact=set(exact_tokens), folded=set(folded_tokens))


def split_vault_note_frontmatter(raw: str) -> ParsedVaultNote:
    """Split leading YAML frontmatter from Markdown body."""
    if not raw.startswith("---"):
        return ParsedVaultNote(metadata={}, body=raw, had_frontmatter=False)

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise VaultFrontmatterParseError("malformed YAML frontmatter")
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise VaultFrontmatterParseError("malformed YAML frontmatter") from exc
    if not isinstance(data, dict):
        raise VaultFrontmatterParseError("frontmatter must be a YAML mapping")
    return ParsedVaultNote(metadata=data, body=raw[match.end() :], had_frontmatter=True)


def strip_markdown_for_snippet(text: str) -> str:
    """Lightly clean Markdown syntax for compact search snippets."""
    stripped = _HEADING_MARKERS_RE.sub("", text)
    stripped = _MARKDOWN_INLINE_RE.sub("", stripped)
    return " ".join(stripped.split())


def score_token_overlap(
    query_tokens: TokenSets, document_tokens: TokenSets, weight: float
) -> float:
    """Score matching overlap between two TokenSets with a 25% exact-match bonus."""
    folded_matches = len(query_tokens.folded & document_tokens.folded)
    exact_matches = len(query_tokens.exact & document_tokens.exact)
    return weight * (folded_matches + 0.25 * exact_matches)


def extract_title_from_body_or_slug(body: str, slug: str) -> str:
    """Extract first heading from note body or fallback to a humanized slug."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    words = re.split(r"[-_\s.]+", slug.strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or slug
