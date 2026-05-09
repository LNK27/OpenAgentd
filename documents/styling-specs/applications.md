---
title: Applications & Templates
description: Component examples — agent chips, sidebar, input bar, tool calls, theme toggle — using paper tokens
status: stable
updated: 2026-05-09
---

# Applications & Templates

Component examples using OpenAgentd paper tokens. All examples work in both modes without modification; brand pigment is reserved for the Octobot mascot, agent identity is carried by the chip palette, and chrome stays warm-neutral.

---

## Agent chips (signature component)

The agent chip is the most-used custom component in the product. It identifies which agent is talking, which role is selected in the topbar, and what kind of work is queued. The chip is a soft pastel pill with an edge dot and a darker text color — the three colors come from `--accent-{role}-soft`, `--accent-{role}` (edge), and `--accent-{role}-text`.

### The four canonical roles

```tsx
// openagentd (router)
<button className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                   bg-(--accent-green-soft) text-(--accent-green-text)
                   text-sm font-medium
                   hover:font-semibold transition-all duration-150">
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-green)" aria-hidden="true" />
  openagentd
</button>

// executor
<button className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                   bg-(--accent-blue-soft) text-(--accent-blue-text)
                   text-sm font-medium
                   hover:font-semibold transition-all duration-150">
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-blue)" aria-hidden="true" />
  executor
</button>

// consultant
<button className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                   bg-(--accent-orange-soft) text-(--accent-orange-text)
                   text-sm font-medium
                   hover:font-semibold transition-all duration-150">
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-orange)" aria-hidden="true" />
  consultant
</button>

// explorer
<button className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                   bg-(--accent-pink-soft) text-(--color-text)
                   text-sm font-medium
                   hover:font-semibold transition-all duration-150">
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-pink)" aria-hidden="true" />
  explorer
</button>
```

### Selected vs unselected

The topbar role toggle uses chips for *all* states — selection is communicated by **pigment, not container shape**:

| State | Treatment |
|---|---|
| **Unselected** | Soft fill + edge dot at full saturation, weight 500 |
| **Selected** | Same soft fill + thicker 1.5px ring in `--accent-{role}` + weight 600 + slight shadow |
| **Hover** | Weight 500→600, no fill change (pigment is already there) |

```tsx
<button
  className={`
    inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
    bg-(--accent-green-soft) text-(--accent-green-text)
    text-sm transition-all duration-150
    ${selected
      ? 'font-semibold ring-[1.5px] ring-(--accent-green) shadow-sm'
      : 'font-medium hover:font-semibold'}
  `}
  aria-pressed={selected}
>
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-green)" />
  openagentd
</button>
```

### Anti-patterns

- ❌ Using a chip color outside its role (mint anywhere except openagentd)
- ❌ Replacing the soft fill with the saturated edge color when "selected" (loses readability)
- ❌ Removing the edge dot (the dot doubles as a status anchor — pulse on streaming, dim when idle)
- ❌ Using chips as buttons that *don't* refer to an agent role

---

## Buttons

### Primary (send)

The primary CTA is the **send button** — paper inverted: warm dark surface, cream text. This is the only place the paper aesthetic flips contrast.

```tsx
<button
  className="bg-(--bg-send) text-(--color-text-on-accent)
             px-4 py-2 rounded-md font-medium
             hover:brightness-110 transition-all duration-150"
>
  Send
</button>
```

### Secondary

```tsx
<button
  className="bg-(--bg-card) text-(--color-text)
             border border-(--border-card)
             px-4 py-2 rounded-md font-medium
             hover:bg-(--bg-key) hover:font-semibold
             transition-all duration-150"
>
  Cancel
</button>
```

### Destructive

```tsx
<button
  className="bg-transparent text-(--color-error)
             border border-(--color-error)/30
             px-4 py-2 rounded-md font-medium
             hover:bg-(--accent-red)/10 hover:font-semibold
             transition-all duration-150"
>
  Delete session
</button>
```

### Ghost

```tsx
<button
  className="text-(--color-text-2) px-3 py-1.5 rounded-md
             hover:text-(--color-text) hover:bg-(--bg-key)
             font-normal hover:font-medium
             transition-all duration-150"
>
  Skip
</button>
```

### Loading

```tsx
<button
  disabled
  className="bg-(--bg-send)/60 text-(--color-text-on-accent)
             px-4 py-2 rounded-md font-medium cursor-not-allowed"
>
  Sending…
</button>
```

### With font-weight transition (signature)

Interactive buttons shift weight on hover and active — see [typography.md](./typography.md#font-weight-transitions-signature-interaction).

```tsx
<button
  className="bg-(--bg-send) text-(--color-text-on-accent)
             px-4 py-2 rounded-md
             font-normal hover:font-medium active:font-semibold
             transition-all duration-150 ease-out"
>
  Send
</button>
```

---

## Card

```tsx
<div
  className="bg-(--bg-card) border border-(--border-card)
             rounded-lg p-6 shadow-[var(--shadow-depth)]"
>
  <h3 className="text-h3 font-semibold text-(--color-text) mb-2">Session title</h3>
  <p className="text-(--color-text-muted) text-sm mb-4">
    Started 3 minutes ago · 2 agents active
  </p>
  <button className="text-(--color-accent) font-normal hover:font-medium transition-all">
    View details →
  </button>
</div>
```

---

## Status indicators

Every status pairs color with an icon or label — never color alone.

```tsx
// Running — pulsing success dot (mint = openagentd's color, also the success state)
<div className="flex items-center gap-2 text-(--color-text-2)">
  <span className="relative flex w-2 h-2">
    <span className="absolute inset-0 bg-(--color-success) rounded-full animate-ping opacity-75" />
    <span className="relative w-2 h-2 bg-(--color-success) rounded-full" />
  </span>
  <span>Running</span>
</div>

// Error
<div className="flex items-center gap-2 text-(--color-error)">
  <AlertCircle className="w-4 h-4" />
  <span>Failed</span>
</div>

// Success (static, non-celebratory)
<div className="flex items-center gap-2 text-(--color-success)">
  <CheckCircle className="w-4 h-4" />
  <span>Completed</span>
</div>

// Pending / queued
<div className="flex items-center gap-2 text-(--accent-orange-text)">
  <Clock className="w-4 h-4" />
  <span>Queued</span>
</div>
```

---

## Forms

### Input field

```tsx
<div className="flex flex-col gap-2">
  <label htmlFor="max-wait" className="text-(--color-text) font-medium text-sm">
    Max wait time (seconds)
  </label>
  <input
    id="max-wait"
    type="number"
    defaultValue={30}
    className="bg-(--bg-input) border border-(--color-border) rounded-md
               px-3 py-2 text-(--color-text) placeholder:text-(--color-text-muted)
               focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--focus-ring)
               focus:border-(--color-accent) transition-colors"
    placeholder="30"
  />
  <p className="text-(--color-text-muted) text-sm">
    Increase for longer-running tool calls.
  </p>
</div>
```

### Textarea (YAML / config)

```tsx
<textarea
  className="bg-(--bg-input) border border-(--color-border) rounded-md
             px-3 py-2 text-(--color-text) font-mono text-sm
             placeholder:text-(--color-text-muted)
             focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--focus-ring)
             focus:border-(--color-accent) transition-colors resize-y min-h-[200px]"
  placeholder="mode: chat&#10;max_wait: 30"
/>
```

### Field with error

```tsx
<div className="flex flex-col gap-2">
  <label htmlFor="name" className="text-(--color-text) font-medium text-sm">
    Session name
  </label>
  <input
    id="name"
    aria-invalid="true"
    aria-describedby="name-error"
    className="bg-(--bg-input) border border-(--color-error) rounded-md
               px-3 py-2 text-(--color-text)
               focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--focus-ring)"
  />
  <p id="name-error" className="text-(--color-error) text-sm flex items-center gap-1.5">
    <AlertCircle className="w-3.5 h-3.5" />
    Name is required.
  </p>
</div>
```

---

## Code block

Syntax colors resolve correctly in both modes via tokens from [colors.md](./colors.md#syntax-highlighting--code).

```tsx
<pre className="bg-(--color-surface) border border-(--color-border) rounded-lg p-4 overflow-x-auto">
  <code className="text-(--color-text) font-mono text-sm leading-relaxed">
    <span className="text-(--color-syn-keyword)">const</span>{' '}
    <span className="text-(--color-text)">agent</span>{' '}
    <span className="text-(--color-syn-operator)">=</span>{' '}
    <span className="text-(--color-syn-keyword)">new</span>{' '}
    <span className="text-(--color-syn-type)">Agent</span>()
    <span className="text-(--color-syn-operator)">.</span>
    <span className="text-(--color-syn-function)">init</span>()
  </code>
</pre>
```

For rendered markdown, use the `.prose` class — styled globally to consume the syntax tokens.

### Inline code

```tsx
<code className="bg-(--bg-key) px-1.5 py-0.5 rounded-xs font-mono text-sm">
  app/agent/mode/chat.py
</code>
```

---

## Empty room (signature empty state)

The canonical empty state — mascot + Caveat callout. This is the "what's on your mind?" screen.

```tsx
<div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
  <img
    src="/brand/octobot-agentd-source.png"
    alt=""
    className="w-24 h-24 select-none"
    draggable={false}
  />
  <h2 className="font-hand text-[44px] leading-none text-(--color-text)">
    what&apos;s on your mind?
  </h2>
</div>
```

Caveat is purely visual here — the screen reader gets nothing. If the empty state needs to convey instructions, add an Inter description below the callout (or replace the Caveat with an Inter heading entirely).

---

## Error state page

```tsx
<div className="flex flex-col items-center justify-center min-h-screen bg-(--bg-page) px-4">
  <AlertCircle className="w-16 h-16 text-(--color-error) mb-4" aria-hidden="true" />
  <h1 className="text-h1 font-bold text-(--color-text) mb-2">Session failed</h1>
  <p className="text-(--color-text-muted) text-center mb-6 max-w-[50ch]">
    Session timeout after 30 seconds. Increase{' '}
    <code className="bg-(--bg-key) px-1.5 py-0.5 rounded-xs font-mono text-sm">max_wait</code>{' '}
    in{' '}
    <code className="bg-(--bg-key) px-1.5 py-0.5 rounded-xs font-mono text-sm">chat.yaml</code>{' '}
    and try again.
  </p>
  <div className="flex gap-3">
    <button className="bg-(--bg-send) text-(--color-text-on-accent) px-4 py-2 rounded-md hover:brightness-110">
      Retry
    </button>
    <a
      href="/docs/troubleshoot"
      className="text-(--color-text-2) hover:text-(--color-text) underline underline-offset-4 self-center"
    >
      Troubleshooting guide →
    </a>
  </div>
</div>
```

---

## Modal / dialog

```tsx
{/* Backdrop */}
<div className="fixed inset-0 bg-(--color-overlay) flex items-center justify-center z-50 animate-in fade-in duration-150">
  {/* Panel */}
  <div
    role="dialog"
    aria-modal="true"
    aria-labelledby="dialog-title"
    className="bg-(--bg-card) border border-(--border-card)
               rounded-lg shadow-2xl w-96 max-w-[90vw]
               animate-in fade-in zoom-in-95 slide-in-from-bottom-2 duration-240"
  >
    <div className="border-b border-(--color-border) px-6 py-4">
      <h2 id="dialog-title" className="text-h3 font-semibold text-(--color-text)">
        Confirm deletion
      </h2>
    </div>

    <div className="px-6 py-4">
      <p className="text-(--color-text-2)">This cannot be undone. Delete this session?</p>
    </div>

    <div className="border-t border-(--color-border) px-6 py-4 flex justify-end gap-3">
      <button className="text-(--color-text-2) hover:text-(--color-text) px-4 py-2 rounded-md transition-colors">
        Cancel
      </button>
      <button className="bg-(--color-error) text-(--color-text-on-accent) px-4 py-2 rounded-md hover:brightness-110 transition-all">
        Delete
      </button>
    </div>
  </div>
</div>
```

Focus is trapped inside the dialog; `Esc` closes it; focus returns to the trigger on close. See [interaction.md](./interaction.md#focus-trap-rules).

---

## Sidebar navigation (expanded)

```tsx
<aside className="w-64 bg-(--bg-sidebar) border-r border-(--border-soft) h-screen overflow-y-auto flex flex-col">
  {/* Brand header */}
  <div className="px-4 py-4 flex items-center gap-2 border-b border-(--border-soft)">
    <img
      src="/brand/openagentd-app-icon.png"
      alt=""
      className="w-7 h-7"
      draggable={false}
    />
    <span className="font-bold text-(--color-text) tracking-tight">OpenAgentd</span>
  </div>

  {/* Primary nav */}
  <nav aria-label="Primary" className="flex flex-col gap-0.5 p-3 flex-1">
    <a
      href="/chat"
      className="flex items-center gap-3 px-3 py-2 rounded-md
                 text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)
                 font-normal hover:font-medium
                 transition-all duration-150"
    >
      <MessageCircle className="w-4 h-4" aria-hidden="true" />
      <span>New chat</span>
    </a>
    <a
      href="/commands"
      aria-current="page"
      className="flex items-center gap-3 px-3 py-2 rounded-md
                 bg-(--bg-key) text-(--color-text) font-medium"
    >
      <Command className="w-4 h-4" aria-hidden="true" />
      <span>Commands</span>
    </a>
    <a
      href="/memory"
      className="flex items-center gap-3 px-3 py-2 rounded-md
                 text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)
                 font-normal hover:font-medium
                 transition-all duration-150"
    >
      <Brain className="w-4 h-4" aria-hidden="true" />
      <span>Memory wiki</span>
    </a>
  </nav>

  {/* Footer */}
  <div className="p-3 border-t border-(--border-soft) flex items-center justify-between">
    <ThemeToggle />
  </div>
</aside>
```

Current page shows `aria-current="page"` + permanent selected styling (the same warm `--bg-key` used as hover). Hover shifts weight (see [typography.md](./typography.md#font-weight-transitions-signature-interaction)).

### Collapsed sidebar

When collapsed, the sidebar shrinks to icon-only. The active item must keep a visible affordance — either the same `--bg-key` fill or a 2px left accent bar in `--color-accent`.

```tsx
<aside className="w-14 bg-(--bg-sidebar) border-r border-(--border-soft) h-screen flex flex-col items-center py-3 gap-1">
  {navItems.map((item) => (
    <a
      key={item.href}
      href={item.href}
      aria-label={item.label}
      aria-current={item.active ? 'page' : undefined}
      className={`
        relative flex items-center justify-center w-9 h-9 rounded-md
        transition-all duration-150
        ${item.active
          ? 'bg-(--bg-key) text-(--color-text)'
          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)'}
      `}
    >
      <item.Icon className="w-4 h-4" aria-hidden="true" />
    </a>
  ))}
</aside>
```

---

## Theme toggle (three-way)

`system` / `light` / `dark`. Persisted to `localStorage`. No flash of wrong theme on load (see [layout.md](./layout.md#mode-switching)).

```tsx
import { Monitor, Sun, Moon } from 'lucide-react';

type Theme = 'system' | 'light' | 'dark';

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem('theme') as Theme) ?? 'system'
  );

  useEffect(() => {
    localStorage.setItem('theme', theme);
    const resolved =
      theme === 'system'
        ? matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : theme;
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(resolved);
  }, [theme]);

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex gap-0.5 bg-(--bg-card) border border-(--border-card) rounded-full p-0.5"
    >
      {(['system', 'light', 'dark'] as const).map((mode) => {
        const Icon = mode === 'system' ? Monitor : mode === 'light' ? Sun : Moon;
        const selected = theme === mode;
        return (
          <button
            key={mode}
            role="radio"
            aria-checked={selected}
            aria-label={`${mode} theme`}
            onClick={() => setTheme(mode)}
            className={`
              flex items-center justify-center w-7 h-7 rounded-full transition-all duration-150
              ${selected
                ? 'bg-(--bg-send) text-(--color-text-on-accent)'
                : 'text-(--color-text-muted) hover:text-(--color-text)'}
            `}
          >
            <Icon className="w-3.5 h-3.5" />
          </button>
        );
      })}
    </div>
  );
}
```

---

## Thinking indicator (streaming)

Full motion spec in [motion.md](./motion.md#thinking-indicator-pulse-dots). Progressive label text named by the agent. The dot color matches the agent's chip edge color.

```tsx
function ThinkingIndicator({ label, role }: { label: string; role?: AgentRole }) {
  const dotColor = role ? `var(--accent-${roleToColor[role]})` : 'var(--color-text-muted)';
  return (
    <div
      className="flex items-center gap-2 text-(--color-text-muted)"
      role="status"
      aria-live="polite"
    >
      <div className="flex gap-1">
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse [animation-delay:0ms]"
          style={{ backgroundColor: dotColor }}
        />
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse [animation-delay:200ms]"
          style={{ backgroundColor: dotColor }}
        />
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse [animation-delay:400ms]"
          style={{ backgroundColor: dotColor }}
        />
      </div>
      <span className="text-sm">{label}</span>
    </div>
  );
}

// Usage — label updates as the agent progresses, dot color identifies the role
<ThinkingIndicator role="openagentd" label="Thinking" />
<ThinkingIndicator role="executor" label="Reading 4 files" />
<ThinkingIndicator role="explorer" label="Searching memory" />
```

---

## Streaming cursor

The blinking cursor that trails live-streamed text. Spec in [motion.md](./motion.md#streaming-cursor-blink).

```tsx
<span className="inline-block w-[0.5ch] h-[1em] bg-(--color-text) align-text-bottom animate-[streaming-cursor_1s_steps(2,end)_infinite]" />
```

```css
@keyframes streaming-cursor {
  0%, 50%   { opacity: 1; }
  51%, 100% { opacity: 0; }
}
```

Remove the cursor the moment streaming ends or a tool call starts. A blinking cursor with no live generation is a bug.

---

## Input bar (floating composer)

The input bar is a **paper pill** floating above the conversation — `--bg-card` with a soft border and `--shadow-depth`. It is draggable via a top-edge grip; position is persisted to `localStorage` (`oa-input-position`); a double-click on the grip resets to bottom-center.

### Surface

```tsx
<div
  className="bg-(--bg-card)/90 backdrop-blur-xl
             border border-(--border-card) shadow-[var(--shadow-depth)]
             rounded-2xl
             px-3 py-2"
>
  {/* grip + textarea + attach + send */}
</div>
```

The pill uses `--radius-2xl` (24px) — the largest radius in the system. It reads as a *physical writing instrument*, not a toolbar.

### States

The pencil documents distinct input bar states; each maps to a small visual cue rather than a different layout:

| State | Cue |
|---|---|
| **Empty** | Placeholder text, send button at reduced opacity |
| **Typing** | Send button at full opacity, character counter (if relevant) |
| **Streaming** | Send button replaced with a stop icon; thin border accent in the active agent's chip color |
| **Queue armed** | Small "Queue" pill prefixed with `+1 message · enqueued`, edge in `--accent-orange` |
| **With attachments** | Attachment chips render adjacent to the pill (above or below per `filesBelow` rule) |
| **Collapsed** | Compressed height when sidebar is collapsed; same surface, less padding |

### Attachment previews

File-attachment chips (images rendered as thumbnails, other files as `FileCard`) live in a row adjacent to the input pill. Three rules keep the composer usable:

1. **Direction is position-dependent** — `FloatingInputBar` computes a `filesBelow` boolean and passes it to `InputBar`:
   - **Default: `true`** — previews render *below* the input pill.
   - **Flips to `false`** only when the panel is docked far from the bottom (`bounds.bottom - panel.bottom ≥ 140px`).
   - Recomputed on mount, `window` resize, drag end, and double-click reset.
2. **Single row with horizontal scroll, never vertical wrap** — `flex flex-nowrap w-max` inside an `overflow-x-auto` container.
3. **Image thumbnails render in *compact* mode** — `max-h-[160px] max-w-[160px]` instead of the default 200×200. Click-to-expand lightbox is unaffected.

### Drag handle

The grip is passed to `InputBar` via the `renderDragHandle` render-prop so that `InputBar` can position it relative to the input pill (not the outer panel). The handle uses `absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2` to sit straddling the pill's top edge.

```tsx
<InputBar
  floating
  filesBelow={filesBelow}
  renderDragHandle={() => (
    <button
      type="button"
      aria-label="Drag input bar (double-click to reset position)"
      title="Drag to move · Double-click to reset"
      onPointerDown={(e) => dragControls.start(e)}
      onDoubleClick={handleReset}
      className="absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-1/2
                 w-12 h-3 flex items-center justify-center
                 rounded-full bg-(--bg-card) border border-(--border-card)
                 text-(--color-text-muted) hover:text-(--color-text)
                 transition-colors"
    >
      <GripHorizontal size={12} aria-hidden="true" />
    </button>
  )}
  {...inputProps}
/>
```

Use framer-motion's `useDragControls` with `dragListener={false}` on the motion wrapper, then start drag manually from the handle's `onPointerDown`. This is the only reliable way to gate drag to a sub-region without breaking pointer events on the rest of the panel.

---

## Draggable panes

The same handle-only drag pattern applies to team view agent panes. Drag is gated to a visible `GripVertical`; the whole panel remains a valid drop target via `onDragOver` / `onDrop` on its root.

```tsx
<div onDragOver={handleDragOver} onDrop={handleDrop} className="relative">
  <div
    draggable
    onDragStart={handleDragStart}
    className="absolute top-2 left-2 cursor-grab"
    aria-label="Reorder pane"
  >
    <GripVertical className="w-4 h-4 text-(--color-text-muted)" />
  </div>
  {/* pane content — selectable, clickable, normal */}
</div>
```

---

## Tool-call row

Slides in from below with a spring ([motion.md](./motion.md#tool-call-row-slide-in)). Tool calls are role-tagged: the wrench icon picks up the calling agent's chip edge color.

### Collapsed (single line)

```tsx
<div
  className="bg-(--bg-card) border border-(--border-card) rounded-md
             px-3 py-2 flex items-center gap-3
             animate-in slide-in-from-bottom-1 fade-in duration-240 ease-out"
>
  <Wrench className="w-4 h-4 text-(--accent-blue)" aria-hidden="true" />
  <span className="text-sm font-mono text-(--color-text-2)">read_file</span>
  <span className="text-sm text-(--color-text-muted) truncate font-mono">
    app/agent/mode/chat.py
  </span>
  <span className="ml-auto text-xs text-(--color-text-muted)">124ms</span>
  <ChevronRight
    className="w-3.5 h-3.5 text-(--color-text-subtle) transition-transform"
    aria-hidden="true"
  />
</div>
```

### Expanded (with output)

```tsx
<div
  className="bg-(--bg-card) border border-(--border-card) rounded-md
             flex flex-col
             animate-in slide-in-from-bottom-1 fade-in duration-240 ease-out"
>
  {/* Header row — same as collapsed */}
  <div className="px-3 py-2 flex items-center gap-3 border-b border-(--border-soft)">
    <Wrench className="w-4 h-4 text-(--accent-blue)" aria-hidden="true" />
    <span className="text-sm font-mono text-(--color-text-2)">read_file</span>
    <span className="text-sm text-(--color-text-muted) truncate font-mono">
      app/agent/mode/chat.py
    </span>
    <span className="ml-auto text-xs text-(--color-text-muted)">124ms</span>
    <ChevronDown className="w-3.5 h-3.5 text-(--color-text-subtle)" aria-hidden="true" />
  </div>

  {/* Output — code block on slightly inset surface */}
  <pre className="px-3 py-2 bg-(--color-tint-mint) text-sm font-mono text-(--color-text) overflow-x-auto">
    <code>{toolOutput}</code>
  </pre>
</div>
```

The output uses `--color-tint-mint` (very-low-alpha mint) as a subtle "this came back successfully" wash — *only* when the call returned `success`. Errors use `--accent-red` at 8% alpha; pending (still executing) uses `--color-tint-orange`.

---

## Queue banner

When messages are enqueued behind a streaming response, a small banner appears above the input bar.

```tsx
<div
  className="flex items-center gap-2 px-3 py-1.5
             bg-(--accent-orange-soft) text-(--accent-orange-text)
             rounded-full text-sm font-medium
             border border-(--accent-orange)/30"
  role="status"
  aria-live="polite"
>
  <span className="w-1.5 h-1.5 rounded-full bg-(--accent-orange)" aria-hidden="true" />
  <span>+1 message · enqueued</span>
  <button className="ml-2 text-(--accent-orange-text)/70 hover:text-(--accent-orange-text)">
    <X className="w-3 h-3" />
  </button>
</div>
```

Orange (consultant chip) is reused here because "enqueued" is conceptually a *consultation* signal — "this will be considered next, not now". The chip-soft / chip-edge / chip-text triad scales to any small status pill.

---

## Design token export (JSON)

For Figma, Storybook, or other design tools:

```json
{
  "mode": {
    "light": {
      "color": {
        "bg-page": "#FAF6EC",
        "bg-sidebar": "#F5EFDD",
        "bg-card": "#FFFBF1",
        "bg-input": "#FAF6EC",
        "bg-key": "#F0E9D4",
        "bg-send": "#2D241B",
        "surface": "#FFFDF7",
        "surface-2": "#F5EBD8",
        "border-soft": "#E8DFC6",
        "border-card": "#E0D5B7",
        "border": "#D7C7AA",
        "border-strong": "#A89880",
        "text": "#1A1714",
        "text-2": "#5F5143",
        "text-muted": "#7A6B58",
        "text-subtle": "#A89880",
        "text-on-accent": "#FFFDF7",
        "accent": "#3F3429",
        "accent-blue": "#5AA8E2",
        "accent-blue-soft": "#DCEEFB",
        "accent-blue-text": "#2D6FA8",
        "accent-green": "#3DA66A",
        "accent-green-soft": "#E2F2E5",
        "accent-green-text": "#2D7A4F",
        "accent-orange": "#F59E3B",
        "accent-orange-soft": "#FFF1D8",
        "accent-orange-text": "#C26A1E",
        "accent-pink": "#E63D7A",
        "accent-pink-soft": "#FBE0EB",
        "accent-purple": "#7C5BCF",
        "accent-purple-soft": "#E8DEF8",
        "accent-red": "#C8333E",
        "marker-blue": "#0284C7",
        "marker-mint": "#16A34A",
        "marker-orange": "#FA8030",
        "marker-pink": "#DB2777",
        "marker-yellow": "#B77900",
        "violet": "#7C3AED",
        "success": "#3DA66A",
        "warning": "#F59E3B",
        "error": "#B91C1C",
        "info": "#5AA8E2",
        "overlay": "#1A171466"
      },
      "focus-ring": "#3F3429",
      "shadow-depth": "0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.05)"
    },
    "dark": {
      "color": {
        "bg-page": "#15110D",
        "bg-sidebar": "#1C1813",
        "bg-card": "#1C1813",
        "bg-input": "#1C1813",
        "bg-key": "#2A2219",
        "bg-send": "#F5EBD8",
        "surface": "#221C16",
        "surface-2": "#2A2219",
        "border-soft": "#2C231A",
        "border-card": "#3A2F23",
        "border": "#3A2F23",
        "border-strong": "#5C4B36",
        "text": "#F5EBD8",
        "text-2": "#C5B59A",
        "text-muted": "#9C8A72",
        "text-subtle": "#7A6B58",
        "text-on-accent": "#15110D",
        "accent": "#F5EBD8",
        "accent-blue": "#7CC2F0",
        "accent-blue-soft": "#1E3A52",
        "accent-blue-text": "#9DD0F5",
        "accent-green": "#5DC487",
        "accent-green-soft": "#1F3A2A",
        "accent-green-text": "#92E0B0",
        "accent-orange": "#FDB75D",
        "accent-orange-soft": "#3D2D14",
        "accent-orange-text": "#FCC780",
        "accent-pink": "#F472B6",
        "accent-pink-soft": "#3D1F2D",
        "accent-purple": "#A78BFA",
        "accent-purple-soft": "#2D2440",
        "accent-red": "#F87171",
        "marker-blue": "#38BDF8",
        "marker-mint": "#4ADE80",
        "marker-orange": "#FCC352",
        "marker-pink": "#F472B6",
        "marker-yellow": "#FBBF24",
        "violet": "#A78BFA",
        "success": "#5DC487",
        "warning": "#FDB75D",
        "error": "#F87171",
        "info": "#7CC2F0",
        "overlay": "#00000099"
      },
      "focus-ring": "#F5EBD8",
      "shadow-depth": "0 1px 2px rgba(0,0,0,0.3), 0 2px 8px rgba(0,0,0,0.25)"
    }
  },
  "typography": {
    "font-sans": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "font-mono": "'JetBrains Mono', ui-monospace, 'SF Mono', 'Courier New', monospace",
    "font-hand": "'Caveat', 'Bradley Hand', cursive",
    "size": {
      "hand": "44px",
      "display": "32px",
      "h1": "28px",
      "h2": "24px",
      "h3": "20px",
      "body": "16px",
      "sm": "14px",
      "xs": "12px"
    },
    "weight": {
      "regular": 400,
      "medium": 500,
      "semibold": 600,
      "bold": 700
    }
  },
  "radius": {
    "xs": "6px",
    "sm": "8px",
    "md": "10px",
    "lg": "14px",
    "2xl": "24px",
    "pill": "999px"
  },
  "spacing": {
    "base": "4px",
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "24px",
    "2xl": "32px",
    "3xl": "48px",
    "4xl": "64px"
  },
  "motion": {
    "duration": {
      "instant": "80ms",
      "fast": "150ms",
      "base": "240ms",
      "slow": "400ms",
      "glacial": "800ms"
    },
    "ease": {
      "out": "cubic-bezier(0.16, 1, 0.3, 1)",
      "in-out": "cubic-bezier(0.4, 0, 0.2, 1)",
      "spring-soft": "cubic-bezier(0.34, 1.2, 0.64, 1)",
      "spring-snappy": "cubic-bezier(0.22, 1.4, 0.36, 1)"
    }
  }
}
```

---

## Pre-ship checklist

- [ ] Tokens used (`--bg-*`, `--color-*`, `--accent-*`, `--fg-*`) — no raw hex values
- [ ] Both modes verified (toggle between light/dark — nothing should look broken)
- [ ] Body uses Inter; code uses JetBrains Mono; Caveat is opt-in only on hand callouts
- [ ] Spacing aligns to 4px base; radius uses `--radius-*`
- [ ] Focus ring visible on `:focus-visible` (tab through the UI to verify)
- [ ] Contrast ≥ 4.5:1 for body text (Lighthouse / WebAIM)
- [ ] Icons from lucide-react, sized to the [imagery.md](./imagery.md#sizing) scale
- [ ] Status colors paired with icon or label (never color alone)
- [ ] Agent chips use the correct `--accent-{role}-*` triad — soft fill, edge dot, text
- [ ] Brand pigment (Octobot gold/orange) only on mascot and lockups, never on UI chrome
- [ ] Motion uses tokens from [motion.md](./motion.md) — no magic ms values
- [ ] Font-weight transitions on interactive elements only (not on Caveat)
- [ ] `prefers-reduced-motion` tested
- [ ] Keyboard navigation works end-to-end (no traps, logical tab order)
- [ ] Touch targets ≥ 44×44 on mobile
- [ ] Empty/error/loading states all present
