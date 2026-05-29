"""Tests for shared vault/wiki markdown text helpers."""

from __future__ import annotations

import pytest

from app.services.markdown_text import (
    VaultFrontmatterParseError,
    extract_title_from_body_or_slug,
    get_token_sets,
    score_token_overlap,
    split_vault_note_frontmatter,
    strip_markdown_for_snippet,
)


def test_split_vault_note_frontmatter_preserves_body_exactly() -> None:
    raw = "---\ntitle: Test\ncustom: value\n---\n# Heading\n\nBody --- stays.\n"

    parsed = split_vault_note_frontmatter(raw)

    assert parsed.metadata == {"title": "Test", "custom": "value"}
    assert parsed.body == "# Heading\n\nBody --- stays.\n"
    assert parsed.had_frontmatter is True


def test_split_vault_note_frontmatter_without_frontmatter_returns_raw_body() -> None:
    raw = "# Heading\n\nBody only.\n"

    parsed = split_vault_note_frontmatter(raw)

    assert parsed.metadata == {}
    assert parsed.body == raw
    assert parsed.had_frontmatter is False


def test_split_vault_note_frontmatter_rejects_malformed_yaml() -> None:
    with pytest.raises(VaultFrontmatterParseError):
        split_vault_note_frontmatter("---\ntitle: [broken\n---\nBody\n")


def test_get_token_sets_supports_vietnamese_and_folded_tokens() -> None:
    tokens = get_token_sets("Đọc note tổng_hợp rest-api")

    assert tokens.exact == {"đọc", "note", "tổng", "hợp", "rest", "api"}
    assert tokens.folded == {"doc", "note", "tong", "hop", "rest", "api"}


def test_strip_markdown_for_snippet_lightly_cleans_markdown() -> None:
    snippet = strip_markdown_for_snippet(
        "# Title\n> quoted text\n- **bold** and `code`\n"
    )

    assert snippet == "Title quoted text bold and code"


def test_score_token_overlap_calculates_with_exact_match_bonus() -> None:
    q = get_token_sets("đọc")
    d1 = get_token_sets("đọc")
    d2 = get_token_sets("doc")

    # exact match reads both exact and folded -> 1 + 0.25 = 1.25
    assert score_token_overlap(q, d1, 1.0) == 1.25
    # folded match but not exact -> 1 + 0 = 1.0
    assert score_token_overlap(q, d2, 1.0) == 1.0


def test_extract_title_from_body_or_slug_extracts_correctly() -> None:
    body_with_h1 = "\n\n# Real Title\nBody content\n"
    assert extract_title_from_body_or_slug(body_with_h1, "slug-name") == "Real Title"

    body_with_h3 = "### H3 Title\nContent"
    assert extract_title_from_body_or_slug(body_with_h3, "slug-name") == "H3 Title"

    body_no_heading = "Just body content\n"
    assert (
        extract_title_from_body_or_slug(body_no_heading, "slug_name_test")
        == "Slug Name Test"
    )
