---
title: Model capabilities registry
status: open
owner: providers
opened: 2026-05-17
updated: 2026-05-18
---

# Tech debt: per-model capability metadata

## Current state

`app/agent/providers/capabilities.py` resolves capability flags via an
**exact-match lookup** against a curated YAML registry shipped inside
the wheel (`app/agent/providers/capabilities.yaml`).

Lookup rule:

1. Exact `provider:model` match in the YAML → those flags, sparse-merged
   onto the all-false defaults.
2. Otherwise → all-false / text-out-only defaults.

There are no prefix fallbacks and no name-substring heuristics. The
YAML is therefore the authoritative document — reading it tells you
exactly what every flagship model can do.

## Why this shape

- **YAML lists only special-capability models.** A model that does
  plain text-in / text-out doesn't need an entry — it gets the right
  defaults by virtue of *not* being listed. That keeps the file small
  and the maintenance question trivial: "does this new model have
  vision / image-output / audio / video?" If no, do nothing.

- **Conservative on unknowns.** An un-curated model can't accidentally
  trip the chat attachment gate or the read tool's image handler. The
  worst-case for a forgotten entry is a vision-capable model refusing
  images until someone notices and adds a one-liner.

- **Fresh on every release.** The YAML ships inside the wheel
  (`[tool.hatch.build.targets.wheel] packages = ["app"]`). Users
  upgrading the CLI (`uv tool upgrade openagentd` / `pip install -U`)
  or the desktop app (Tauri auto-update) get the new file atomically
  as part of package replacement — no merge, no migration, no init
  step. The YAML deliberately does *not* live under
  `{OPENAGENTD_CONFIG_DIR}` to avoid the "user copy shadows the bundle
  forever" trap that bites our agents/skills/`mcp.json` seeds.

## Why the previous prefix-fallback design was discarded

The interim design (commits before this one) resolved capabilities by
longest-prefix match on the `provider:` portion of the ID, e.g.
`openai:` → vision-true, `deepseek:` → vision-false. That was simpler
than a per-model table but had two failure modes:

- **Over-permissive.** `openai:text-embedding-3-small` inherited
  vision=true from the `openai:` prefix and would only fail at the
  upload boundary if a user actually attached an image to a request
  bound for an embedding endpoint.
- **Over-conservative.** `bedrock:` defaulted to vision=false because
  Bedrock hosts both vision (Claude 4.x, Nova) and text-only (Titan
  small) models. Real Claude-on-Bedrock requests rejected image
  attachments needlessly.

The exact-match table fixes both — but only as long as someone keeps
the YAML current, which is the actual tech debt.

## Long-term direction

If we ever need richer per-model metadata (context length,
image-output, audio in/out, thinking levels, etc.), or if the curation
burden becomes painful, replace the YAML with a **runtime-fetched
registry**. The clearest reference is CLIProxyAPI's `models.json`:

- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/models/models.json>
- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/model_definitions.go>

That schema carries `display_name`, `context_length`,
`max_completion_tokens`, `supportedGenerationMethods`,
`thinking: {min, max, levels}`, and `supported_parameters` per model,
grouped by channel/provider.

If we adopt it:

- Replace the YAML resolver with a JSON registry fetched at daemon
  startup (and cached on disk with a TTL for offline use).
- Hot-refresh from a URL we control, the way CLIProxyAPI does
  (`model_updater.go`).
- Keep an embedded snapshot of the JSON as the offline-fallback so
  first-launch / air-gapped installs still resolve common models.

## Out of scope until then

- Re-introducing prefix fallbacks or name-substring heuristics. They
  drift faster than provider catalogs evolve.
- Per-user override files at `{OPENAGENTD_CONFIG_DIR}/capabilities.yaml`.
  If users start asking for that, it's the signal that the curated
  YAML is too stale and we should be doing the runtime-fetched
  registry instead.

## Symptoms that warrant prioritising this

- The YAML grows past ~200 entries and PRs adding new models start
  blocking on review latency.
- Users routinely surprised that a model is missing a capability the
  provider already supports.
- Need for any capability beyond the current axes (e.g. routing on
  context length, gating reasoning effort, distinguishing
  image-generation vs. chat models).
