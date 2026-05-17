---
title: Trim catalog default_models
status: open
owner: providers
opened: 2026-05-18
---

# Tech debt: shrink `catalog.py` to the structural metadata only

## Current state

`app/agent/providers/catalog.py` carries five things per provider:

1. **Credential shape** (`kind`, `env_var`, `env_vars`) — drives how the
   providers page renders inputs / OAuth buttons / daemon status.
2. **OAuth command hint** (`oauth_command`) — CLI fallback for OAuth
   providers.
3. **Docs URL** (`docs_url`) — link to the provider's API-key
   dashboard.
4. **Display metadata** (`label`, `description`).
5. **`default_models`** — curated fallback list shown when live model
   discovery is unavailable.

Items 1–4 are structural and have no alternative source — the catalog
is the only place that knows OpenAI's env var is `OPENAI_API_KEY` and
xAI's is `XAI_API_KEY`. They stay.

Item 5 is the problem. `default_models` duplicates information that
the provider's own `/v1/models` endpoint can serve, and goes stale
exactly the same way `capabilities.yaml` used to go stale — between
releases. The recent xAI fix (Grok 4.3 vs Grok 4 retirement) is a
concrete example.

## What to do

Once live discovery via `app/agent/providers/model_discovery.py` is
considered reliable for the common providers (OpenAI, Google,
OpenRouter, Z.AI, NVIDIA, xAI, DeepSeek), trim `default_models` to the
*minimum* required for the providers that genuinely can't be
discovered:

- **Bedrock** — no `/v1/models` listing endpoint via STS-auth path.
- **Codex / Copilot OAuth** — fixed roster, provider-side.
- **Vertex AI** — `aiplatform.googleapis.com` has a models listing
  but it requires extra setup; current `default_models` is the
  shortest path.

For everything else, the UI behaviour becomes:

- No credentials yet → empty list, "Click 'List models' to verify
  your key" prompt.
- Credentials entered → live discovery populates the list.
- Discovery fails → toast says so. Don't fake a fallback list.

That eliminates the "Why does the providers page still list Grok 4 in
the dropdown when xAI retired it?" failure mode entirely.

## Why not do it now

- The current providers-page UX expects *some* list to render
  pre-discovery so the "empty until you save credentials" flow needs a
  small redesign.
- Live discovery's error paths aren't currently audited end-to-end for
  every provider — some return malformed payloads or different shapes.
  Walking that catalogue is a separate piece of work.

## Symptoms that warrant prioritising

- More than two model-staleness corrections to `default_models` in a
  single quarter.
- A user-reported confusion about a model showing in the dropdown that
  doesn't actually work.
- The catalog file grows past ~300 lines because someone keeps
  re-syncing it to provider websites.
