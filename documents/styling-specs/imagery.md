---
title: Imagery & Graphics
description: Octobot mascot, lucide icons, charts on the marker palette, agent chips, screenshots, patterns
status: stable
updated: 2026-05-09
---

# Imagery & Graphics

## Iconography

## Mascot and brand imagery

OpenAgentd uses the Octobot mascot from `documents/assets/brand/octobot-agentd-source.png` as the single source of truth. Do not redraw, simplify, or replace the mascot with a generic robot/octopus. Source-faithful lockups live in `documents/assets/brand/`; app-imported copies live in `web/src/assets/brand/`.

Use the full-color mascot for:

- README and social headers
- Empty states and onboarding moments — paired with a Caveat callout (`what's on your mind?`) on the empty room screen
- App icon, sidebar logo, and avatar-style surfaces
- Launch or release graphics

The mascot's warm gold/orange pigments are designed for the paper page (`--bg-page` / `#FAF6EC`) — they will desaturate on cool gray surfaces. Always render against paper, Shell White, or Console Ink (see [logo.md](./logo.md#palette)).

Avoid using the mascot as decoration in dense product chrome. In the app UI, small repeated logo positions should use `openagentd-app-icon.png`; larger quiet empty states can use `octobot-agentd-source.png` at full opacity (the warm paper provides enough quietness on its own — fading the mascot tends to muddy the linework).

### Library: lucide-react

Single icon library, no mixing. `lucide-react` ships with the web stack and provides consistent 24px-native outlined icons with 1.5–2px strokes.

```tsx
import { Play, AlertCircle, CheckCircle } from 'lucide-react';
```

### Sizing

| Size | Use case |
|------|----------|
| **16px** | Status indicators, inline icons, table cells, small metadata |
| **20px** | Dense lists, secondary buttons |
| **24px** | Default UI icons, nav, primary buttons |
| **32px** | Feature tiles, section headers |
| **48px** | Empty-state illustrations, hero moments |

### Color

| Context | Color |
|---------|-------|
| Default | `currentColor` (inherits from text) |
| Interactive hover | `var(--color-accent)` |
| Agent role indicator | matching `--accent-{role}` edge color (e.g. `--accent-green` for openagentd) |
| Status — success | `var(--color-success)` |
| Status — warning | `var(--color-warning)` |
| Status — error | `var(--color-error)` |
| Status — info | `var(--color-info)` |
| Disabled | `var(--color-text-subtle)` |

### Rules

- **Outlined only** — never mix outlined and filled icons in the same view
- **Stroke width**: default (stock lucide). Don't override unless the icon looks visually too thin at a specific size.
- **Icon + label pairing**: when an icon accompanies text, don't duplicate meaning (`<Delete />` + "Delete" is fine; `<Info />` + "Info" is redundant — use a visible text label or an icon-only button with `aria-label`)
- **Icon-only buttons**: require `aria-label` or a tooltip for accessibility

### Example

```tsx
// Default, inherits text color
<Play className="w-6 h-6" />

// Interactive — shifts to accent on hover
<Play className="w-6 h-6 text-text hover:text-accent transition-colors" />

// Status
<CheckCircle className="w-6 h-6 text-success" aria-label="Running" />
<AlertCircle className="w-6 h-6 text-error" aria-label="Error" />
```

---

## Patterns & textures

### No decorative patterns, no gradients in chrome

Backgrounds are **solid warm neutrals**. No grid overlays, no dot patterns, no noise textures, no parallax layers. The paper aesthetic intentionally avoids gradients in UI chrome — the only gradients in the system live inside the mascot artwork itself.

| Context | Treatment |
|---|---|
| Page background | `var(--bg-page)` solid |
| Panel / sidebar | `var(--bg-sidebar)` solid |
| Card / popover | `var(--bg-card)` solid + `var(--shadow-depth)` |
| Elevated surface | `var(--color-surface)` solid + `var(--shadow-depth)` |
| Section tint (rare) | `var(--accent-{role}-soft)` — only for content tied to that agent role |

### Dividers & borders

- **Subtle divider**: 1px solid `var(--border-soft)` — between list rows
- **Default divider**: 1px solid `var(--color-border)` — between sections, on cards
- **Strong divider**: 1px solid `var(--color-border-strong)` — major section breaks
- **Never**: gradient borders, dashed borders for decoration (dashed is reserved for *drag-target* affordances and *queued* states)

### Drag-target highlight

```css
.drag-target {
  outline: 2px dashed color-mix(in srgb, var(--color-accent) 55%, transparent);
  outline-offset: 2px;
  background: color-mix(in srgb, var(--color-accent) 6%, transparent);
}
```

---

## Data visualization

### Tools

- **Primary**: Recharts (already in the web stack)
- **Secondary**: Chart.js for advanced visualizations that Recharts can't handle well
- **Not used**: custom hand-rolled SVG charts without accessibility review

### Color palette

Use the **marker palette** from [colors.md](./colors.md#marker-palette--charts-and-tints). Markers are slightly more saturated than agent chips because they need to read against busy chart backgrounds. Series 1 is always the most prominent data, series 5 the least.

```ts
// Resolve via CSS custom properties — values flip per mode automatically
const chartColors = [
  'var(--color-marker-blue)',   // 1
  'var(--color-marker-mint)',   // 2
  'var(--color-marker-orange)', // 3
  'var(--color-marker-pink)',   // 4
  'var(--color-marker-yellow)', // 5
];

// Area fills use the matching tint (low-alpha)
const tintFills = [
  'var(--color-tint-mint)',
  'var(--color-tint-orange)',
  'var(--color-tint-violet)',
];
```

**Never** use the Octobot brand gold/orange as a chart color unless the data explicitly represents OpenAgentd itself. **Never** use the agent chip colors as chart series — chips are role-identity-reserved, and reusing them in charts will collide perceptually with chip badges on the same screen.

### Design rules

- **Minimize non-data ink** — remove gridlines where possible, lighten axis labels to `text-muted`
- **No rainbow palettes** — stick to 3–5 series max; if you need more, stack or facet the chart
- **No pie charts** — bar or donut charts communicate proportion more accurately
- **Always provide a legend** for multi-series charts
- **Accessibility**: never rely on color alone. Pair series with patterns, symbols, or direct labels.
- **Responsive**: scale axis labels down at `< 640px`; hide secondary axes on mobile

### Example (Recharts area chart)

```tsx
<AreaChart data={data}>
  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
  <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={12} />
  <YAxis stroke="var(--color-text-muted)" fontSize={12} />
  <Tooltip
    contentStyle={{
      background: 'var(--color-surface)',
      border: '1px solid var(--color-border)',
      borderRadius: 8,
    }}
  />
  <Area
    type="monotone"
    dataKey="requests"
    stroke="var(--color-marker-blue)"
    fill="var(--color-marker-blue)"
    fillOpacity={0.2}
  />
</AreaChart>
```

---

## Markdown & prose

The app uses a custom `.prose` class for rendered markdown.

| Element | Style |
|---|---|
| `h1`–`h3` | `--color-text`, 600–700 weight, large top margin |
| Body | `--color-text`, 1.6 line-height, `max-width: 65ch` |
| `code` (inline) | `--color-text` on `--bg-key`, 6px radius (`--radius-xs`), JetBrains Mono, 0.9em |
| `pre code` (block) | `--color-surface` background, 1px `--color-border`, JetBrains Mono, syntax highlighted |
| Links | `--color-accent` with underline at 2px offset; weight 400→500 on hover |
| Lists | 1.5em padding, disc (ul) / decimal (ol) |
| Blockquote | Left border 3px `--color-border-strong`, `--color-text-2`, 1em padding |
| Tables | 1px `--color-border`, `--color-surface-2` header background |
| `hr` | 1px `--color-border-subtle` |

---

## Empty states

### Structure

The canonical empty state pairs the **mascot** with a **Caveat callout** — this is the "what's on your mind?" moment from the empty room screen.

1. Mascot — 64–96px, `octobot-agentd-source.png`, full color
2. Callout — Caveat (`--font-hand`), 32–44px, `--color-text`, lowercase, ends with a question mark or period
3. (Optional) Subtle Inter description — Body, `--color-text-muted`, `max-width: 40ch`
4. (Optional) Primary CTA only when there's a clear next action

```tsx
<div className="flex flex-col items-center justify-center py-12 gap-4">
  <img src="/brand/octobot-agentd-source.png" alt="" className="w-20 h-20" />
  <h2 className="font-hand text-[40px] leading-none text-(--color-text)">
    what&apos;s on your mind?
  </h2>
</div>
```

For more utilitarian empty states (no mascot, no Caveat — e.g. "No memory items yet"):

```tsx
<div className="flex flex-col items-center justify-center py-12">
  <Inbox className="w-12 h-12 text-(--color-text-muted) mb-4" aria-hidden="true" />
  <h2 className="text-h3 font-semibold text-(--color-text) mb-2">
    No sessions yet
  </h2>
  <p className="text-(--color-text-muted) text-center mb-6 max-w-[40ch]">
    Create a session to start working with agents.
  </p>
  <button className="bg-(--bg-send) text-(--color-text-on-accent) px-4 py-2 rounded-md hover:brightness-110">
    Create session
  </button>
</div>
```

### Skeleton placeholders

For content that will load within a few hundred milliseconds:

- Background: `var(--bg-key)` (warmer than `--color-surface-2`, so skeleton blocks read as "paper waiting for ink")
- Pulse animation: opacity `0.6 ↔ 1.0` over 1400ms (honors `prefers-reduced-motion`)
- Shape: match the final content's dimensions to prevent layout shift

```css
@keyframes skeleton-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.6; }
}

.skeleton {
  background: var(--bg-key);
  border-radius: var(--radius-sm);
  animation: skeleton-pulse 1400ms ease-in-out infinite;
}
```

Skeletons longer than ~800ms should be replaced with progressive text (see [motion.md](./motion.md#principles)).

---

## Screenshots

### Mode choice

Light (paper) is the canonical mode and the default everywhere unless there's a specific reason to use dark.

| Context | Mode |
|---|---|
| Product marketing (hero, landing, social cards) | **Light (paper)** — the warm cream is the brand surface |
| Documentation | **Light** |
| API reference screenshots | **Light** |
| README | **Light** |
| Blog posts | Match the blog's theme (usually light for long-form reading) |
| Conference slides on dark stages | **Dark** — for legibility against a dark venue |
| "What it looks like at night" feature | **Dark** |

### Composition

- **Crop tight** — screenshots should show the feature, not the browser chrome (unless the chrome is part of the point)
- **Consistent chrome** — if multiple screenshots appear together, use the same window style across all of them
- **Real data** — never use "Lorem ipsum" placeholder text in screenshots. Use plausible session names, real file paths, believable agent output.
- **No annotations inside the screenshot** — if you need arrows or labels, add them as a layer *on top* of the screenshot at export time, not inside the UI

### Export

- **1× and 2×** PNG for web
- **SVG** when the screenshot is actually a vector mockup (rare)
- **Full-bleed** or framed with 24px padding on a `--bg-page` background — pick one convention per surface and stick to it
