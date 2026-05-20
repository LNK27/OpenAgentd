---
title: Slash commands
description: Reusable prompt templates triggered with `/name` in the chat input. Compatible with opencode's command format.
status: stable
updated: 2026-05-20
---

# Slash commands

Slash commands are short, named prompt templates. Type `/` in the chat
input to open the picker, choose one, append any arguments, and submit —
the rendered body is sent as your user message.

The format is intentionally the same as
[opencode's commands](https://opencode.ai), so a library you've built
for one tool works in the other without duplication.

## File format

Each command is a `.md` file with optional YAML frontmatter:

```markdown
---
description: Make a commit with a conventional message.
---

Run `git status --porcelain`. Stage everything if nothing is staged.
Produce a conventional commit message describing: $ARGUMENTS
```

- `description` (optional) — shown in the picker.
- `$ARGUMENTS` (optional) — replaced with whatever the user typed after
  the command name. If absent and arguments are supplied, they are
  appended to the body on a new line.

The filename (minus `.md`) becomes the command id. Nested folders are
preserved as `/`-separated names — `commands/git/commit.md` registers
as `git/commit`.

## Where commands live

Discovery walks four roots in this order — first match wins on a name
collision:

| # | Root | Source label | Use it for |
|---|------|--------------|------------|
| 1 | `{cwd}/.openagentd/commands/` | `project-openagentd` | Project-specific, OpenAgentd-native |
| 2 | `{cwd}/.opencode/commands/`   | `project-opencode`   | Reuse an opencode project library |
| 3 | `{OPENAGENTD_CONFIG_DIR}/commands/` | `global-openagentd` | Your personal library |
| 4 | `~/.config/opencode/commands/` | `global-opencode`   | Reuse your global opencode library |

`{cwd}` is the working directory the OpenAgentd server was launched
from — in coding mode this is your project root, so `/commit` can mean
different things in different projects without manual switching.

## Picker behaviour

- **Built-in commands** (`/stop`, `/continue`, `/compact`, `/undo`, `/redo`, `/new`) execute immediately on pick.
  `/continue` resumes the last assistant response; `/compact` runs the session summarizer; `/undo` reverts the latest user turn, restores its workspace snapshot, and puts the text back in the composer; `/redo` restores all undone turns sequentially, replaying the workspace forward to the live tip.
- **Discovered commands** insert `/<name> ` into the textarea so you
  can type arguments before submitting.

When you submit a message starting with `/`, the backend renders the
template and sends the expanded body to the agent. The picker closes
once you type a space, so the menu does not get in the way while you
write arguments.

## API

| Method & path | Purpose |
|---------------|---------|
| `GET /api/commands` | List discovered commands with `name`, `description`, `source`. Sorted alphabetically. |
| `POST /api/commands/{name}/render` | Body `{"arguments": "..."}` returns `{"name": ..., "content": <rendered body>}`. Nested names (`git/commit`) are allowed in the path. |

## Example

`~/.config/openagentd/commands/git/commit.md`:

```markdown
---
description: Stage, analyse the diff, and write a conventional commit.
---

Run `git status --porcelain`. If no files are staged, run `git add .`.
Then `git diff --cached`, summarise the changes, and produce a
conventional-commits message describing: $ARGUMENTS
```

Then in chat:

```
/git/commit fix off-by-one in cursor decoder
```

The agent receives the full rendered prompt, not the `/git/commit …`
line.
