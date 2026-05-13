"""Reconstruct the full LLM payload for an agent — no server required.

Produces the exact things sent to the provider on every request:
  1. system_prompt        — base prompt + skills section + date injection
  2. system_prompt_final  — same, after ``WikiInjectionHook`` has appended
                            ``wiki/USER.md`` (what the LLM actually sees).
                            Requires the configured wiki dir to exist on disk
                            (``.openagentd/wiki/`` in dev,
                            ``~/.local/share/openagentd-wiki/`` in production).
  3. tools                — JSON array of tool definitions (as sent in the API body)

Output is a single JSON object:
  {
    "system_prompt": "...",
    "system_prompt_final": "...",
    "wiki_user_block": "...",
    "tools": [...],
    "stats": { ... }
  }

Paste system_prompt_final + tools JSON into https://platform.openai.com/tokenizer
(or tiktoken) to get an accurate token count.

Usage:
  uv run python -m manual.inspect_prompt
  uv run python -m manual.inspect_prompt --dir .openagentd/agents
  uv run python -m manual.inspect_prompt --agent explorer
  uv run python -m manual.inspect_prompt --no-date
  uv run python -m manual.inspect_prompt --date 2026-04-12
  uv run python -m manual.inspect_prompt --out .openagentd/chat/payload.json
  uv run python -m manual.inspect_prompt --stats-only
  uv run python -m manual.inspect_prompt --no-wiki              # skip WikiInjectionHook
  uv run python -m manual.inspect_prompt --wiki-only            # print just USER.md block
  uv run python -m manual.inspect_prompt --final-only           # print just the final prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _default_agents_dir() -> str:
    """Resolve the agents directory from settings.

    Falls back to ``.openagentd/config/agents`` (dev-mode default) if settings
    fail to import for some reason.
    """
    try:
        from app.core.config import settings

        return settings.AGENTS_DIR
    except Exception:
        return ".openagentd/config/agents"


DEFAULT_AGENTS_DIR = _default_agents_dir()


# ── Loader helpers ────────────────────────────────────────────────────────────


def _build_skills_section(skills: list[str]) -> str:
    """Replicate loader._build_skills_section() exactly."""
    from app.agent.tools.builtin.skill import discover_skills

    available = discover_skills()
    lines = ["\n## Available skills\n"]
    for skill_name in skills:
        meta = available.get(skill_name, {})
        desc = meta.get("description", "(no description)")
        lines.append(f"- **{skill_name}**: {desc}")
    lines += [
        "",
        "Call `skill` with the skill name to load its full instructions.",
    ]
    return "\n".join(lines)


def _build_tool_definitions(tool_names: list[str]) -> list[dict]:
    """Return tool definition dicts in the order the agent sends them."""
    from app.agent.loader import _default_tool_registry
    from app.agent.tools.builtin.skill import load_skill as _load_skill_tool

    registry = _default_tool_registry()

    # skill tool is always prepended (mirrors loader._build_agent)
    tools = [registry.get("skill", _load_skill_tool)]

    for name in tool_names:
        if name == "skill":
            continue
        if name not in registry:
            print(f"Warning: unknown tool '{name}' — skipped", file=sys.stderr)
            continue
        tools.append(registry[name])

    return [t.definition for t in tools]


def _inject_date(prompt: str, date_str: str) -> str:
    """Replicate inject_current_date hook."""
    return f"{prompt}\n\nCurrent date (UTC): {date_str}"


def _build_wiki_user_block() -> str:
    """Invoke WikiInjectionHook's read path — exactly what the hook injects.

    Returns an empty string when ``wiki/USER.md`` does not exist (or fails to
    read), mirroring the hook's real behaviour.  Topic content is *not*
    injected — the runtime hook also stopped doing that; agents call the
    ``wiki_search`` tool explicitly when they need topic context.
    """
    from app.agent.hooks.wiki_injection import WikiInjectionHook

    hook = WikiInjectionHook()
    user_block = hook._read_user_md()
    if not user_block:
        return ""
    return "## About the user\n\n" + user_block


def _apply_wiki_injection(system_prompt: str, wiki_user_block: str) -> str:
    """Replicate WikiInjectionHook.wrap_model_call's prompt merge."""
    if not wiki_user_block:
        return system_prompt
    if system_prompt:
        return f"{system_prompt}\n\n{wiki_user_block}"
    return wiki_user_block


# ── Stats ─────────────────────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token (GPT-3/4 average for English+JSON)."""
    return len(text) // 4


def _print_stats(
    system_prompt: str,
    system_prompt_final: str,
    wiki_user_block: str,
    tools_json: str,
    agent: str,
    model: str,
) -> None:
    sp_chars = len(system_prompt)
    final_chars = len(system_prompt_final)
    wiki_chars = len(wiki_user_block)
    t_chars = len(tools_json)
    total = final_chars + t_chars
    print(f"\nAgent: {agent}  model: {model}", file=sys.stderr)
    print(
        f"  system_prompt       : {sp_chars:>7,} chars  (~{_estimate_tokens(system_prompt):,} tokens)",
        file=sys.stderr,
    )
    print(
        f"  wiki USER.md block  : {wiki_chars:>7,} chars  (~{_estimate_tokens(wiki_user_block):,} tokens)",
        file=sys.stderr,
    )
    print(
        f"  tools JSON          : {t_chars:>7,} chars  (~{_estimate_tokens(tools_json):,} tokens)",
        file=sys.stderr,
    )
    print(
        f"  tool_count          : {tools_json.count('"type": "function"')}",
        file=sys.stderr,
    )
    print(f"  {'─' * 49}", file=sys.stderr)
    print(
        f"  system_prompt_final : {final_chars:>7,} chars  (~{_estimate_tokens(system_prompt_final):,} tokens)",
        file=sys.stderr,
    )
    print(
        f"  total (final+tools) : {total:>7,} chars  (~{_estimate_tokens(system_prompt_final + tools_json):,} tokens)",
        file=sys.stderr,
    )
    print(file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(
        description="Reconstruct the full LLM payload (system prompt + tools) for an agent"
    )
    p.add_argument(
        "--dir",
        default=DEFAULT_AGENTS_DIR,
        metavar="DIR",
        help=f"Agents directory with .md files (default: {DEFAULT_AGENTS_DIR})",
    )
    p.add_argument(
        "--agent",
        metavar="NAME",
        help="Agent name to inspect (default: lead agent)",
    )
    p.add_argument(
        "--no-date",
        action="store_true",
        help="Skip date injection (show base prompt only)",
    )
    p.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Override injected date (default: today UTC)",
    )
    p.add_argument(
        "--out",
        metavar="FILE",
        help="Write JSON output to a file instead of stdout",
    )
    p.add_argument(
        "--stats-only",
        action="store_true",
        help="Print char/token estimates only — no JSON output",
    )
    p.add_argument(
        "--no-wiki",
        "--no-memory",  # legacy alias
        dest="no_wiki",
        action="store_true",
        help="Skip WikiInjectionHook — show base prompt only (no USER.md block)",
    )
    p.add_argument(
        "--wiki-only",
        "--memory-only",  # legacy alias
        dest="wiki_only",
        action="store_true",
        help="Print just the injected wiki USER.md block (plain text) and exit",
    )
    p.add_argument(
        "--final-only",
        action="store_true",
        help="Print just the final system_prompt (after hook injection) and exit",
    )
    args = p.parse_args()

    agents_dir = Path(args.dir)
    if not agents_dir.exists():
        print(f"Error: agents directory not found: {agents_dir}", file=sys.stderr)
        sys.exit(1)

    from app.agent.loader import parse_agent_md

    md_files = sorted(agents_dir.glob("*.md"))
    if not md_files:
        print(f"Error: no .md files in {agents_dir}", file=sys.stderr)
        sys.exit(1)

    configs = []
    for md_path in md_files:
        try:
            cfg = parse_agent_md(md_path)
            configs.append(cfg)
        except Exception as exc:
            print(f"Warning: failed to parse {md_path.name}: {exc}", file=sys.stderr)

    if not configs:
        print("Error: no valid agent configs found", file=sys.stderr)
        sys.exit(1)

    # Select agent
    if args.agent:
        matches = [c for c in configs if c.name == args.agent]
        if not matches:
            names = [c.name for c in configs]
            print(
                f"Error: agent '{args.agent}' not found. Available: {names}",
                file=sys.stderr,
            )
            sys.exit(1)
        agent_cfg = matches[0]
    else:
        # Default to lead
        leads = [c for c in configs if c.role == "lead"]
        agent_cfg = leads[0] if leads else configs[0]

    # List all discovered agents
    print(f"\nDiscovered agents in {agents_dir}:", file=sys.stderr)
    for cfg in configs:
        marker = " <--" if cfg.name == agent_cfg.name else ""
        print(
            f"  {cfg.name:15s} role={cfg.role:6s} model={cfg.model or '(none)'}{marker}",
            file=sys.stderr,
        )
    print(file=sys.stderr)

    # 1. System prompt
    system_prompt = agent_cfg.system_prompt
    if agent_cfg.skills:
        system_prompt += _build_skills_section(agent_cfg.skills)

    # 2. Date injection
    if not args.no_date:
        date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system_prompt = _inject_date(system_prompt, date_str)

    # 3. Wiki USER.md injection (WikiInjectionHook.wrap_model_call)
    if args.no_wiki:
        wiki_user_block = ""
    else:
        try:
            wiki_user_block = _build_wiki_user_block()
        except Exception as exc:
            print(f"Warning: wiki USER.md injection failed: {exc}", file=sys.stderr)
            wiki_user_block = ""
    system_prompt_final = _apply_wiki_injection(system_prompt, wiki_user_block)

    # Early exits for focused inspection
    if args.wiki_only:
        if not wiki_user_block:
            print(
                "(no wiki USER.md block — wiki/USER.md missing or --no-wiki set)",
                file=sys.stderr,
            )
            sys.exit(1)
        print(wiki_user_block)
        return
    if args.final_only:
        print(system_prompt_final)
        return

    # 4. Tool definitions
    tool_defs = _build_tool_definitions(agent_cfg.tools)
    tools_json = json.dumps(tool_defs, indent=2, ensure_ascii=False)

    payload = {
        "system_prompt": system_prompt,
        "wiki_user_block": wiki_user_block,
        "system_prompt_final": system_prompt_final,
        "tools": tool_defs,
        "stats": {
            "system_prompt_chars": len(system_prompt),
            "wiki_user_block_chars": len(wiki_user_block),
            "system_prompt_final_chars": len(system_prompt_final),
            "tools_json_chars": len(tools_json),
            "total_chars": len(system_prompt_final) + len(tools_json),
            "tool_count": len(tool_defs),
            "agent": agent_cfg.name,
            "model": agent_cfg.model,
            "role": agent_cfg.role,
            "wiki_user_injected": bool(wiki_user_block),
        },
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Written to {out_path}", file=sys.stderr)
    elif not args.stats_only:
        print(output)

    # Print stats last so they appear as a summary after the JSON payload
    _print_stats(
        system_prompt,
        system_prompt_final,
        wiki_user_block,
        tools_json,
        agent_cfg.name,
        agent_cfg.model or "(none)",
    )


if __name__ == "__main__":
    main()
