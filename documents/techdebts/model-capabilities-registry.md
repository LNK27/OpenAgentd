---
title: Model capabilities registry
status: open
owner: providers
opened: 2026-05-17
---

# Tech debt: per-model capability metadata

## Current state

`app/agent/providers/capabilities.py` resolves vision / document / output
flags from **provider prefix only**. There are no per-model overrides
and no name-substring heuristics. Edge cases surface as a provider-side
error on first use.

Concretely:

- The `bedrock:` prefix defaults to `vision=false`. Real-world Bedrock
  hosts both vision-capable (Claude 4.x, Nova Pro) and text-only (Titan,
  Nova Micro) models — the prefix default rejects image attachments for
  every Bedrock model, even ones that would accept them.
- The `openai:` prefix defaults to `vision=true`. Discovered models
  like `openai:text-embedding-3-small` inherit that and would only fail
  at upload if the user actually attaches an image.
- The `ollama:` prefix defaults to `vision=false`; running `llava`
  through Ollama needs the user to know it's vision-capable, since the
  attachment gate will reject images.

The user-visible result: the **attachment-upload gate**
(`app/services/agent_service.py:325`) and the **read tool's image
handler** (`app/agent/tools/builtin/filesystem/read.py:37`) are
conservative on prefixes that span both modes, and permissive on
prefixes that don't.

## Why we accepted this

The previous design carried:

- `capabilities.yaml` — per-model exact overrides, ~190 lines, grew
  with every provider model release.
- `_VISION_MARKERS` / `_TEXT_ONLY_MARKERS` — name-substring heuristics
  that classified live-discovered models. Wrong on edge cases
  (`claude-instant` is not vision; `gemini-embedding-001` is not
  vision; etc.).

Both were maintenance hot-spots: each new provider model required a
human to decide "does this need a YAML entry?" or "does this trip the
substring heuristic correctly?". The YAML was also redundant for the
hot path — most agents end up running a flagship model where the prefix
default already gives the right answer.

Trimming the system back to prefix-only:

- Deletes ~150 lines of capability code and the entire YAML.
- Removes a class of subtle bugs (heuristics misclassifying edge cases).
- Matches the system's existing "we don't curate a model catalog"
  philosophy (`providers.md` already says model IDs are passed
  verbatim).

## Long-term direction

If we ever need richer per-model metadata (context length, image-output,
thinking levels, etc.), adopt a **single curated JSON registry** rather
than re-introducing scattered overrides + heuristics. The clearest
reference is CLIProxyAPI's `models.json`:

- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/models/models.json>
- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/model_definitions.go>

That schema carries `display_name`, `context_length`,
`max_completion_tokens`, `supportedGenerationMethods`,
`thinking: {min, max, levels}`, and `supported_parameters` per model,
grouped by channel/provider.

If we adopt it:

- Replace `_PREFIX_FALLBACKS` and `get_capabilities` with a JSON lookup.
- Optionally hot-refresh from a remote URL the way CLIProxyAPI does
  (`model_updater.go`).
- Keep the prefix table as a final fallback so unknown models don't
  break.

## Out of scope until then

- Re-introducing `capabilities.yaml` or any other per-model override
  file. If you find yourself wanting to "just pin one model", that's
  the trigger to design the JSON registry instead.
- Name-substring heuristics. They drift faster than provider catalogs
  evolve.

## Symptoms that warrant prioritising this

- Users routinely surprised that an attached image was rejected by a
  Bedrock or Ollama model they know is vision-capable.
- Need for any capability beyond vision (e.g. routing decisions based
  on context length, gating reasoning effort, distinguishing
  image-generation vs. chat models).
- A new provider whose model namespace doesn't cleanly map to a single
  prefix default.
