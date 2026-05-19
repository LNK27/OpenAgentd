---
name: mcp-installer
description: >-
  Install, update, remove, or restart Model Context Protocol (MCP) servers
  in `{OPENAGENTD_CONFIG_DIR}/mcp.json`. Use when the user asks to add / remove /
  list / restart an MCP, or to enable a server like filesystem, github,
  postgres, puppeteer, brave-search.
---

# MCP Installer

Use **`mcp_apply.py`** — a script bundled in this skill directory — for all
MCP operations. It wraps the daemon API so you don't construct curl commands
by hand.

```bash
# The script lives next to this SKILL.md:
SCRIPT="{SKILL_DIR}/mcp_apply.py"

python3 "$SCRIPT" <command> [options]
```

The script talks to the daemon at `http://localhost:4082/api/mcp` by default.
Pass `--base <url>` to override.

## Commands

```bash
# Add a remote HTTP server
python "$SCRIPT" add <name> --http <url>

# Add an OAuth HTTP server. Paste credential values; the API stores them
# as <SERVER>_MCP_CLIENT_ID / <SERVER>_MCP_CLIENT_SECRET in .env and writes
# ${...} refs to mcp.json. Omit values for dynamic-registration servers.
python "$SCRIPT" add <name> --http <url> --oauth
python "$SCRIPT" add slack --http https://mcp.slack.com/mcp \
  --oauth-client-id <client-id> --oauth-client-secret <client-secret>

# Add a stdio server
python "$SCRIPT" add <name> --stdio <command> --args arg1 arg2 --env KEY=VALUE

# Update an existing server
python "$SCRIPT" update <name> --http <url>
python "$SCRIPT" update <name> --stdio <command> --args ...

# Remove a server
python "$SCRIPT" remove <name>

# Restart a runner (no config change)
python "$SCRIPT" restart <name>

# Start an explicit OAuth browser flow
python "$SCRIPT" connect-oauth <name>

# Re-read mcp.json and reconcile all runners
python3 "$SCRIPT" apply

# Check state of one or all servers
python3 "$SCRIPT" status [<name>]

# Poll until a server is ready (useful after add/update)
python3 "$SCRIPT" wait <name> [--timeout 30]
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success — or daemon unreachable but `mcp.json` updated as fallback |
| `1` | API / validation error — detail on stderr |
| `2` | Server ended up in `error` or still needs OAuth (`auth_required`) |
| `3` | `wait` timed out — server still `starting` |

`add`, `update`, `remove`, and `apply` never exit 1 on connection refused —
they fall back to editing `mcp.json` directly and exit 0. The agent can
always proceed to wiring after these commands regardless of daemon state.

## When to use

| User intent                                  | Command                                      |
| -------------------------------------------- | -------------------------------------------- |
| Install / update a remote (HTTP) server      | `add` or `update` with `--http`              |
| Install / update a local (stdio) server      | `add` or `update` with `--stdio`             |
| Remove a server                              | `remove` — but wire agent files first        |
| Restart a crashed server                     | `restart`                                    |
| Re-read mcp.json after manual edit           | `apply`                                      |
| Check what's running                         | `status`                                     |
| Attach server tools to an agent              | **Call `skill("self-healing")`** after add   |

## Workflow — install / update

1. **Handle secrets safely** before installing servers that need them:

   - For stdio servers that read env vars directly, confirm the env var exists with `printenv KEY | head -c 4`. Empty → tell the user to add it to `{OPENAGENTD_CONFIG_DIR}/.env`; don't install a server you know will fail.
   - For HTTP OAuth servers, ask the user for the app client ID/secret when required. Pass the pasted values with `--oauth-client-id` / `--oauth-client-secret`; the API stores only generated `<SERVER>_MCP_CLIENT_ID` / `<SERVER>_MCP_CLIENT_SECRET` keys in `{OPENAGENTD_CONFIG_DIR}/.env` and writes `${...}` refs to `mcp.json`.
   - For dynamic-registration OAuth servers such as Notion, use `--oauth` without credential values.

2. **Expand `~` and relative paths** for stdio args — the daemon spawns under
   its own cwd. Use `realpath`:

   ```bash
   realpath ~/Documents   # → /Users/<you>/Documents
   ```

3. **Add or update** the server:

   ```bash
   # Remote HTTP (preferred when the server offers a hosted URL)
   python3 "$SCRIPT" add excalidraw --http https://mcp.excalidraw.com

   # HTTP OAuth, dynamic registration
   python3 "$SCRIPT" add notion --http https://mcp.notion.com/mcp --oauth

   # HTTP OAuth, app credentials required
   python3 "$SCRIPT" add slack --http https://mcp.slack.com/mcp \
     --oauth-client-id <client-id> --oauth-client-secret <client-secret>

   # Local stdio
   python3 "$SCRIPT" add filesystem --stdio npx \
     --args -y @modelcontextprotocol/server-filesystem /Users/you/Documents
   ```

   - Exit `0`: runner started (may still be `starting` — use `wait` if needed).
   - Exit `1`: API validation error — fix the config and retry.
   - Exit `2`: runner hit `error` or `auth_required` — show the error, fix
     config or run `connect-oauth`, then retry.

4. **Connect OAuth if needed.** If status is `auth_required`, run the explicit
   browser flow:

   ```bash
   python3 "$SCRIPT" connect-oauth <name>
   ```

5. **Wait for ready** (optional but recommended):

   ```bash
   python3 "$SCRIPT" wait excalidraw --timeout 30
   ```

6. **Wire into an agent.** Installing alone does NOT make the tools callable.
   This step is **mandatory** — do not consider the install complete until done.

   **The lead must wire it.** Two paths:

   - **Member target (fast path)**: call `team_configure(member="<handle>", action="add", kind="mcp", name="<server>")` directly. One tool call, validates against the live registry, takes effect on the member's next turn.
   - **Lead target, or any non-trivial multi-field edit**: call `skill("self-healing")` and follow its diff workflow.

   Do not delegate this step to a member agent, even if the member ran the steps above.

   Only skip if the user explicitly says they will wire it manually.

## Workflow — removal

1. **Strip agent references first.** Check all agent files:

   ```bash
   rg '<name>' {OPENAGENTD_CONFIG_DIR}/agents/
   ```

   If any agent has the server in `mcp:` or `mcp_<name>_*` in `tools:`,
   **call `skill("self-healing")`** to remove those entries *before* removing
   the server. Otherwise the next-turn rebuild logs `agent_config_refresh_failed`.

2. **Remove the server:**

   ```bash
   python3 "$SCRIPT" remove <name>
   ```

## Common servers

| Name         | Command                                                             |
| ------------ | ------------------------------------------------------------------- |
| filesystem   | `--stdio npx --args -y @modelcontextprotocol/server-filesystem <path>` |
| github       | `--stdio npx --args -y @modelcontextprotocol/server-github` (needs token env) |
| brave-search | `--stdio npx --args -y @modelcontextprotocol/server-brave-search` (needs key env) |
| postgres     | `--stdio npx --args -y @modelcontextprotocol/server-postgres <conn-string>` |
| sqlite       | `--stdio uvx --args mcp-server-sqlite --db-path <path>` |
| excalidraw   | `--http https://mcp.excalidraw.com` |
| notion       | `--http https://mcp.notion.com/mcp --oauth`, then `connect-oauth notion` |
| slack        | `--http https://mcp.slack.com/mcp --oauth-client-id <id> --oauth-client-secret <secret>`, then `connect-oauth slack` |

Verify package names with the user — npm names drift.

## Failure modes

- **Exit 2 (`error`)** → show the error field; suggest the obvious fix
  (missing package, wrong path, missing env var). Don't retry blindly.
- **`auth_required` state** → run `connect-oauth <name>`. If it still returns
  a conflict, ask for the missing OAuth app credentials and update the server.
- **Exit 0 with "daemon unreachable" message** → `mcp.json` was updated
  as fallback. Proceed to step 6 (wire into agent) as normal. Changes
  take effect on next daemon restart.
- **`agent_config_refresh_failed`** (next turn's logs) → an agent's `tools:`
  list references a removed tool. Run `rg 'mcp_' {OPENAGENTD_CONFIG_DIR}/agents/`
  then call `skill("self-healing")`.

A failing MCP server does NOT block other servers, the team, or any
in-flight turn — tell the user that, they often assume the worst.
