# MCP Runtime Observability Port v2 Design

## Summary

Port MCP runtime observability onto the synced `main` MCP manager without reusing the old patch mechanically. The current manager has newer OAuth and streamable HTTP behavior, so v2 adds a small status-only observability layer around the current lifecycle code.

The goal is operator visibility: restart counts, last restart reason/time, last failure time, and flapping warnings. It does not add UI, persistence, metrics, or new tool execution semantics.

## Current Code Shape

`app/agent/mcp/manager.py` currently owns one `_ServerRunner` per configured MCP server. `_run_server()` opens stdio or streamable HTTP transport, initializes `ClientSession`, calls `list_tools()`, sets status to `ready`, then waits for shutdown.

Important current boundaries:

- HTTP MCP supports OAuth and can end in `auth_required`.
- `restart_server()` stops and respawns one runner from disk config.
- `reload_from_config()` tears down all runners and rebuilds from config.
- `/api/mcp/servers` and `/api/mcp/servers/{name}` project `MCPServerStatus` through `ServerStatusResponse`.
- There is currently no watchdog retry loop on the synced main branch.

## Approaches Considered

### Approach 1: Status-Only Extension In Manager

Add observability fields directly to `MCPServerStatus`, expose them through the existing MCP status API, and implement watchdog/flapping state inside `MCPManager`.

Pros:

- Smallest API blast radius.
- No new route, database, UI, or background service.
- Fits the existing route shape and operator status endpoint.
- Keeps tool execution and permission gate untouched.

Cons:

- No historical event timeline.
- Status resets on process restart.

### Approach 2: Per-Runner Event Ring Buffer

Add a bounded in-memory event list per server with restart/failure events and expose it through a new API route.

Pros:

- Better debugging detail.
- Can show exact restart sequence.

Cons:

- Adds route/schema surface and retention policy.
- Higher test and privacy burden.
- More than needed for v2.

### Approach 3: Metrics/Tracing First

Emit Prometheus counters and OTel spans for MCP restarts/failures without changing status API.

Pros:

- Good for dashboards later.
- Low-cardinality counters are straightforward.

Cons:

- Does not help the current `/api/mcp/servers` operator surface.
- Adds observability backend coupling before the status problem is solved.

## Recommendation

Use Approach 1.

MCP Runtime Observability Port v2 should be a status-only extension to the current manager. It gives the operator the missing restart/flapping information while preserving the new OAuth/HTTP architecture and avoiding new API/UI/persistence scope.

## Status Fields

Add these defaulted fields to `MCPServerStatus` and `ServerStatusResponse`:

- `auto_restart_count: int = 0`
- `manual_restart_count: int = 0`
- `last_restart_reason: str | None = None`
- `last_restart_at: str | None = None`
- `last_failure_at: str | None = None`
- `flapping: bool = False`
- `warning: str | None = None`

The existing `state` comment should include `auth_required` because the current code already uses it.

All new fields are status data only. They do not change MCP tool names, tool execution, OAuth behavior, permission gates, or saved `mcp.json`.

## Tool Call Activity Boundary

The liveness monitor must not call `session.list_tools()` while the same MCP session is handling a tool call. The current code has two live tool-call paths:

- generated MCP tools through `MCPTool._invoke()`
- MCP app bridge calls through `MCPManager.call_app_tool()`

v2 should track tool-call activity inside `_ServerRunner` and route both paths through the same tracked session wrapper. The wrapper increments/decrements an internal active-call counter around `call_tool()` while preserving the existing call surface for `MCPTool` and app bridge consumers.

The activity gate must prevent liveness probes from overlapping with active tool calls without serializing normal tool calls against each other. Multiple tool calls may still run concurrently as they do today; only liveness probes are mutually excluded from tool-call windows.

The raw MCP SDK `ClientSession` should stay local to the `_run_server()` task and its async context. The runner may expose a small tracked wrapper that implements only `call_tool()`, and `MCPTool` should type its session provider against that minimal protocol rather than the concrete SDK session.

Required behavior:

- if one or more tool calls are active, liveness skips that interval instead of probing
- if a liveness probe is already in progress, a new tool call waits until the short probe completes
- liveness failures are considered only when no tool call is active during the probe
- active-call counters and probe flags are internal runtime state only and are not exposed in the API response

## Watchdog Semantics

The current `_run_server()` single-attempt lifecycle should become a retrying lifecycle:

1. Attempt to connect and initialize the server.
2. On `ready`, keep the transport/session contexts open.
3. Run a liveness monitor while ready, guarded by the tool-call activity boundary above.
4. If initialization or liveness fails with a non-auth runtime failure, mark failure and retry with bounded backoff.
5. If retries exceed the cap, leave the server in `error`.
6. If shutdown is requested, exit cleanly without incrementing restart counters.

Constants:

- `MCP_WATCHDOG_MAX_RETRIES = 5`
- `MCP_FLAPPING_RESTART_THRESHOLD = 3`
- `MCP_STABLE_WINDOW_SECONDS = 60.0`
- `MCP_LIVENESS_INTERVAL_SECONDS = 5.0`
- Backoff starts at 1 second and caps at 30 seconds.

`auto_restart_count` increments only when the manager actually schedules a watchdog retry. Initial start attempts that succeed without retry do not increment it.

`last_failure_at` is set on non-auth runtime failures. `last_restart_reason` becomes `watchdog_retry` when an automatic retry is scheduled. `last_restart_at` records when the retry is scheduled.

Flapping is `true` when the current consecutive retry count reaches `MCP_FLAPPING_RESTART_THRESHOLD`. The warning should be a stable string such as `mcp_server_flapping`.

When the liveness monitor observes successful health checks for longer than `MCP_STABLE_WINDOW_SECONDS`, it resets consecutive retry count, clears `flapping`, and clears `warning`. This avoids stale warnings after a server recovers and stays healthy.

The retry count should remain owned by the `_run_server()` loop. Do not pass retry state through getter/setter callbacks into `_run_server_once()`. `_run_server_once()` should either return cleanly on shutdown or raise a concrete runtime/auth exception back to the retry loop.

## OAuth/Auth Boundary

OAuth and auth-required paths are terminal for that attempt and must not enter watchdog retry:

- explicit `OAuthRequiredError`
- HTTP missing-token/auth failures currently converted to `auth_required`
- OAuth registration failure / unresolved OAuth client-id paths

These paths should set `state="auth_required"`, set `error`, clear tools/session, and set `ready`. They should not increment `auto_restart_count`, should not mark flapping, and should not set `last_restart_reason`.

## Manual Restart Inheritance

`restart_server(name)` currently stops the old runner and spawns a new runner, which would lose in-memory status history. v2 should preserve observability history:

- capture old status before stop
- stop old runner
- spawn disabled or enabled runner based on current config
- copy `auto_restart_count`, `manual_restart_count`, `last_failure_at`, `flapping`, and `warning`
- increment `manual_restart_count`
- set `last_restart_reason="manual_restart"`
- set `last_restart_at` to current UTC timestamp

Manual restart should preserve history for disabled targets too. Disabled runners still end in `state="stopped"` with inherited counters.

`reload_from_config()` is a full config reconciliation and does not need to preserve per-runner history in v2. That keeps the feature small and avoids stale data after config shape changes.

## API Surface

No new route is added. Existing responses include the new fields:

- `GET /api/mcp/servers`
- `GET /api/mcp/servers/{name}`
- `POST /api/mcp/servers`
- `PUT /api/mcp/servers/{name}`
- `POST /api/mcp/servers/{name}/restart`
- `POST /api/mcp/servers/{name}/oauth/connect`
- `POST /api/mcp/apply`

The fields have defaults, so older tests and consumers that ignore extra response fields remain compatible.

## Privacy And Safety

Do not record env vars, OAuth tokens, headers, URLs with secrets, tool arguments, or tool result content in the new status fields.

Safe values:

- server name
- transport
- status state
- stable restart reason enum
- ISO timestamps
- counters
- boolean flapping flag
- stable warning string

## Out Of Scope

- UI/dashboard changes
- Prometheus or OTel metrics
- persistence or database storage
- restart history event log
- new API routes
- permission gate changes
- MCP tool execution changes
- automatic OAuth retries for auth-required servers
- changing `mcp.json` semantics

## Testing Strategy

Use TDD.

Manager tests should cover:

- new status defaults
- API schema projection of new fields
- manual restart inheritance and counter increment
- disabled manual restart inheritance
- non-auth initialization failure retries and increments auto restart count
- liveness failure after ready triggers retry
- liveness skips probes while a generated MCP tool call is active
- liveness skips probes while an MCP app bridge call is active
- flapping is set after threshold
- flapping clears after a stable liveness window
- OAuth/auth-required paths do not auto-retry or flap

Route tests should cover:

- list/get/restart responses include new observability fields
- defaults serialize as expected

Regression tests should include existing MCP manager and MCP route tests.
