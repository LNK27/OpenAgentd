---
title: Logo Specifications
description: Source-faithful Octobot mascot, lockups, sizing rules, clear space, asset delivery — rendered against warm paper surfaces
status: stable
updated: 2026-05-09
---

# Logo Specifications

## Primary logo

- **Format**: Original Octobot mascot + `OpenAgentd` wordmark
- **Mascot source**: `documents/assets/brand/octobot-agentd-source.png`
- **Canonical assets**: `documents/assets/brand/`
- **App assets**: `web/src/assets/brand/`
- **Wordmark casing**: `OpenAgentd`
- **Wordmark font**: Inter, 800 weight (`--font-sans`)
- **Positioning**: mascot left, wordmark and agent-runtime copy right
- **Default surface**: warm paper (`--bg-page` / `#FAF6EC`). The mascot's warm gold/orange pigments were composed against this tone; rendering on a cool gray neutral will desaturate the mascot perceptually.

The Octobot is the brand. Do not redraw it into a generic robot, simplify the tentacles, replace the eyes, or change the proportions. New assets must embed or directly derive from the source PNG.

---

## Logo variants

| Variant | File | Use |
|---------|------|-----|
| **Primary lockup** | `openagentd-primary-lockup.png` | README, docs, landing pages, wide marketing surfaces |
| **Stacked badge** | `openagentd-stacked-badge.png` | Square cards, social avatars, release graphics |
| **App icon** | `openagentd-app-icon.png` | Transparent mascot icon for sidebar logo, app chrome, and tight UI logo spots |
| **Social header** | `openagentd-social-header.png` | OpenGraph images, social banners, project headers |
| **Source mascot** | `octobot-agentd-source.png` | Empty states, illustrations, source derivation |

Use PNG exports as the canonical delivery format because the mascot source is raster and SVG image references can render inconsistently across browsers, README renderers, and export tools.

---

## Brand copy inside lockups

Prefer agent-centered language:

- `On-machine agent orchestration runtime`
- `Tools + memory + teams + observability`
- `LOCAL AGENT RUNTIME`
- `Build, run, and observe local AI agents.`

Do not lead brand assets with implementation technologies such as FastAPI or React. Those belong in technical docs, not identity lockups.

When text appears inside a filled pill, badge, or bordered container, center it both visually and structurally (`text-anchor="middle"`, `dominant-baseline="middle"` in SVG; flex center in UI code).

---

## Palette

| Name | Hex | Usage |
|------|-----|-------|
| Agent Gold | `#FCC352` | Primary brand surface, badges, brand emphasis |
| Loop Orange | `#FA8030` | Energy accent, selected brand details |
| Kernel Brown | `#5F2511` | Mascot linework, text on gold, warm dark contrast |
| Shell White | `#FBF8F7` | Light brand surfaces and mascot highlights |
| Console Ink | `#17120F` | Dark brand surfaces |

The product UI uses warm-neutral paper tones (see [colors.md](./colors.md)); the brand assets carry the saturated Octobot palette. The two are designed to coexist — `--bg-page` (`#FAF6EC`) sits intentionally close to Shell White (`#FBF8F7`), so a brand asset placed on a product page reads as continuous rather than pasted-on.

**Do not use the Octobot pigments as UI accents.** The warm dark `--color-accent` (`#3F3429`) handles primary affordances; agent identity uses the chip palette (mint / blue / orange / pink) — see [colors.md](./colors.md#agent-chip-palette). Brand pigment is identity-reserved.

---

## Clear Space & Sizing

### Clear Space

Maintain clear space equal to the Octobot eye diameter around the mascot or full lockup. Nothing should intersect the tentacles, antenna, or wordmark area.

### Minimum Size

- **Primary lockup**: 320px wide minimum in digital contexts
- **Stacked badge**: 96px square minimum
- **App icon**: 16px minimum, though 32px+ is preferred
- **Source mascot in empty states**: 48px minimum

At very small sizes, use `openagentd-app-icon.png` instead of the full lockup.

---

## Logo No-Nos

Do not:

- Redraw the mascot from memory
- Use the old stickman assets
- Use the old `o.` monogram direction
- Mention implementation technologies in logo lockups
- Distort, crop, mirror, or recolor the mascot paths
- Put non-centered text inside filled pills or badges
- Add unrelated decorative patterns behind the mascot
- Replace the warm palette with generic blue/purple SaaS colors
- Use the mascot as a repeated background texture
- Render the lockup on a cool gray surface — use `--bg-page`, Shell White, or Console Ink

---

## Asset Delivery

| Format | Use Case | Specs |
|--------|----------|-------|
| **PNG** | Web, docs previews, app UI, slide decks | Canonical exported format for source-faithful mascot assets |
| **ICO / ICNS** | Favicon, app launchers | Use a platform-specific background if required by the target icon format |

Use Pencil for brand-board composition and visual review. Final checked-in exports live in `documents/assets/brand/`; app-imported assets live in `web/src/assets/brand/`; direct browser URL assets such as the favicon live in `web/public/brand-assets/`.
