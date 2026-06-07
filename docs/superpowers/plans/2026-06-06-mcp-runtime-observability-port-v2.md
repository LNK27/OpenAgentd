# MCP Runtime Observability Port v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add status-only MCP restart/flapping observability on the synced `main` MCP manager without changing MCP tool execution, OAuth semantics, permission gates, UI, or persistence.

**Architecture:** Extend `MCPServerStatus` and `ServerStatusResponse`, add an internal activity gate so liveness probes never overlap active tool calls, then add a bounded retry/liveness loop inside `MCPManager` that updates status fields. OAuth/auth-required paths remain terminal and are excluded from watchdog retry.

**Tech Stack:** Python 3.14, asyncio, dataclasses, FastAPI, Pydantic v2, pytest, ruff, ty.

---

## File Structure

- Modify `app/agent/mcp/manager.py`
  - Add status fields.
  - Add `_ServerRunner` activity fields and a tracked session wrapper for `call_tool()`.
  - Add watchdog constants and small helper methods.
  - Reshape `_run_server()` into retry loop plus one-attempt connection helper.
  - Preserve observability history across `restart_server()`.
- Modify `app/agent/mcp/tools.py`
  - Replace the narrow `ClientSession` session-provider type with a small protocol requiring only `call_tool()`.
  - Keep runtime behavior unchanged; this is a typing boundary so the tracked wrapper is valid.
- Modify `app/api/schemas/mcp.py`
  - Add matching response fields with defaults.
- Modify `app/api/routes/mcp.py`
  - Project new status fields in `_to_response()`.
- Modify `tests/agent/mcp/test_manager.py`
  - Add status default, manual restart, watchdog, flapping, and auth boundary tests.
- Modify `tests/api/test_mcp_routes.py`
  - Add route serialization checks for the new fields.
- Modify `.agent/memory/CONTEXT_SNAPSHOT.md`
  - Record whether port v2 is implemented or blocked after verification.

## Task 1: Status Fields And API Projection

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Modify: `app/api/schemas/mcp.py`
- Modify: `app/api/routes/mcp.py`
- Test: `tests/agent/mcp/test_manager.py`
- Test: `tests/api/test_mcp_routes.py`

- [ ] **Step 1: Write failing manager status default test**

Add to `tests/agent/mcp/test_manager.py`:

```python
class TestMCPRuntimeObservabilityStatus:
    def test_status_observability_defaults(self) -> None:
        status = MCPServerStatus(
            name="browser-use",
            transport="stdio",
            enabled=True,
            state="starting",
        )

        assert status.auto_restart_count == 0
        assert status.manual_restart_count == 0
        assert status.last_restart_reason is None
        assert status.last_restart_at is None
        assert status.last_failure_at is None
        assert status.flapping is False
        assert status.warning is None
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_status_observability_defaults --no-cov -q
```

Expected: fail with `AttributeError` for `auto_restart_count`.

- [ ] **Step 3: Add fields to `MCPServerStatus`**

In `app/agent/mcp/manager.py`, update `MCPServerStatus`:

```python
@dataclass
class MCPServerStatus:
    """Live state for one MCP server. Returned by ``GET /api/mcp/servers``."""

    name: str
    transport: str
    enabled: bool
    state: str  # "stopped" | "starting" | "ready" | "error" | "auth_required"
    error: str | None = None
    tool_names: list[str] = field(default_factory=list)
    started_at: str | None = None
    auto_restart_count: int = 0
    manual_restart_count: int = 0
    last_restart_reason: str | None = None
    last_restart_at: str | None = None
    last_failure_at: str | None = None
    flapping: bool = False
    warning: str | None = None
```

- [ ] **Step 4: Verify status default test passes**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_status_observability_defaults --no-cov -q
```

Expected: pass.

- [ ] **Step 5: Write failing route serialization test**

Add to `tests/api/test_mcp_routes.py` inside `TestListServers`:

```python
    def test_list_servers_includes_runtime_observability_fields(self) -> None:
        app = _make_app()
        with patch("app.api.routes.mcp.mcp_manager") as mock_manager:
            status = MCPServerStatus(
                name="browser-use",
                transport="stdio",
                enabled=True,
                state="error",
                auto_restart_count=3,
                manual_restart_count=1,
                last_restart_reason="watchdog_retry",
                last_restart_at="2026-06-06T01:02:03+00:00",
                last_failure_at="2026-06-06T01:02:02+00:00",
                flapping=True,
                warning="mcp_server_flapping",
            )
            mock_manager.list_status.return_value = [status]
            client = TestClient(app)

            response = client.get("/api/mcp/servers")

        assert response.status_code == 200
        server = response.json()["servers"][0]
        assert server["auto_restart_count"] == 3
        assert server["manual_restart_count"] == 1
        assert server["last_restart_reason"] == "watchdog_retry"
        assert server["last_restart_at"] == "2026-06-06T01:02:03+00:00"
        assert server["last_failure_at"] == "2026-06-06T01:02:02+00:00"
        assert server["flapping"] is True
        assert server["warning"] == "mcp_server_flapping"
```

- [ ] **Step 6: Run the failing route test**

Run:

```powershell
uv run pytest tests/api/test_mcp_routes.py::TestListServers::test_list_servers_includes_runtime_observability_fields --no-cov -q
```

Expected: fail because response fields are missing.

- [ ] **Step 7: Add schema and route projection**

In `app/api/schemas/mcp.py`, add fields to `ServerStatusResponse`:

```python
    auto_restart_count: int = 0
    manual_restart_count: int = 0
    last_restart_reason: str | None = None
    last_restart_at: str | None = None
    last_failure_at: str | None = None
    flapping: bool = False
    warning: str | None = None
```

In `app/api/routes/mcp.py`, add these arguments to `_to_response()`:

```python
        auto_restart_count=status.auto_restart_count,
        manual_restart_count=status.manual_restart_count,
        last_restart_reason=status.last_restart_reason,
        last_restart_at=status.last_restart_at,
        last_failure_at=status.last_failure_at,
        flapping=status.flapping,
        warning=status.warning,
```

- [ ] **Step 8: Run Task 1 tests**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus tests/api/test_mcp_routes.py::TestListServers::test_list_servers_includes_runtime_observability_fields --no-cov -q
```

Expected: both pass.

## Task 2: Manual Restart History Inheritance

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Modify: `app/agent/mcp/tools.py`
- Test: `tests/agent/mcp/test_manager.py`

- [ ] **Step 1: Write failing manual restart inheritance test**

Add to `TestMCPRuntimeObservabilityStatus`:

```python
    @pytest.mark.asyncio
    async def test_manual_restart_preserves_observability_history(self) -> None:
        manager = MCPManager()

        async def mock_run_server(name, server_cfg, runner):
            runner.status.state = "ready"
            runner.ready.set()
            await runner.shutdown.wait()

        with patch("app.agent.mcp.manager.load_config") as mock_load:
            cfg = MCPConfig(
                servers={"browser-use": StdioServerConfig(command="echo")}
            )
            mock_load.return_value = cfg
            with patch.object(manager, "_run_server", side_effect=mock_run_server):
                await manager.start()
                old = manager._runners["browser-use"].status
                old.auto_restart_count = 2
                old.manual_restart_count = 4
                old.last_failure_at = "2026-06-06T00:00:00+00:00"
                old.flapping = True
                old.warning = "mcp_server_flapping"

                status = await manager.restart_server("browser-use")

                assert status.auto_restart_count == 2
                assert status.manual_restart_count == 5
                assert status.last_restart_reason == "manual_restart"
                assert status.last_restart_at is not None
                assert status.last_failure_at == "2026-06-06T00:00:00+00:00"
                assert status.flapping is True
                assert status.warning == "mcp_server_flapping"

                await manager.stop()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_manual_restart_preserves_observability_history --no-cov -q
```

Expected: fail because the new runner resets counters.

- [ ] **Step 3: Implement observability copy helpers**

Add helpers to `MCPManager`:

```python
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _copy_observability_history(
        source: MCPServerStatus | None, target: MCPServerStatus
    ) -> None:
        if source is None:
            return
        target.auto_restart_count = source.auto_restart_count
        target.manual_restart_count = source.manual_restart_count
        target.last_failure_at = source.last_failure_at
        target.flapping = source.flapping
        target.warning = source.warning

    def _mark_manual_restart(self, status: MCPServerStatus) -> None:
        status.manual_restart_count += 1
        status.last_restart_reason = "manual_restart"
        status.last_restart_at = self._now_iso()
```

- [ ] **Step 4: Use helpers in `restart_server()`**

Inside `restart_server()`, capture old status before `_stop_runner(name)`, then copy history and mark manual restart after spawning or creating disabled runner:

```python
        async with self._lock:
            old_runner = self._runners.get(name)
            old_status = old_runner.status if old_runner else None
            await self._stop_runner(name)
            server_cfg = cfg.servers[name]
            if not server_cfg.enabled:
                self._runners[name] = self._make_disabled_runner(name, server_cfg)
            else:
                await self._spawn_runner(name, server_cfg)
            new_status = self._runners[name].status
            self._copy_observability_history(old_status, new_status)
            self._mark_manual_restart(new_status)
```

- [ ] **Step 5: Run manual restart test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_manual_restart_preserves_observability_history --no-cov -q
```

Expected: pass.

## Task 3: Active Tool-Call Gate For Liveness Safety

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Test: `tests/agent/mcp/test_manager.py`

- [ ] **Step 1: Write failing activity-gate unit test**

Add to `TestMCPRuntimeObservabilityStatus`:

```python
    @pytest.mark.asyncio
    async def test_liveness_probe_is_skipped_while_tool_call_is_active(self) -> None:
        from app.agent.mcp.manager import _ServerRunner, _TrackedMCPClientSession

        manager = MCPManager()
        runner = _ServerRunner(
            shutdown=asyncio.Event(),
            ready=asyncio.Event(),
            status=MCPServerStatus(
                name="browser-use",
                transport="stdio",
                enabled=True,
                state="ready",
            ),
        )
        call_started = asyncio.Event()
        finish_call = asyncio.Event()

        class RawSession:
            async def call_tool(self, tool_name, arguments):
                call_started.set()
                await finish_call.wait()
                return {"content": []}

        tracked = _TrackedMCPClientSession(manager, runner, RawSession())
        call_task = asyncio.create_task(tracked.call_tool("navigate", {}))
        await asyncio.wait_for(call_started.wait(), timeout=1.0)

        assert runner.active_tool_call_count == 1
        assert await manager._begin_liveness_probe(runner) is False

        finish_call.set()
        await call_task
        assert runner.active_tool_call_count == 0
        assert await manager._begin_liveness_probe(runner) is True
        await manager._end_liveness_probe(runner)

    @pytest.mark.asyncio
    async def test_app_bridge_tool_call_uses_activity_gate(self) -> None:
        from app.agent.mcp.manager import _ServerRunner, _TrackedMCPClientSession

        manager = MCPManager()
        runner = _ServerRunner(
            shutdown=asyncio.Event(),
            ready=asyncio.Event(),
            status=MCPServerStatus(
                name="browser-use",
                transport="stdio",
                enabled=True,
                state="ready",
            ),
            tools=[SimpleNamespace(name="mcp_browser-use_navigate")],
        )
        call_started = asyncio.Event()
        finish_call = asyncio.Event()

        class RawSession:
            async def call_tool(self, tool_name, arguments):
                call_started.set()
                await finish_call.wait()
                return {"content": []}

        runner.session = _TrackedMCPClientSession(manager, runner, RawSession())
        manager._runners["browser-use"] = runner

        call_task = asyncio.create_task(
            manager.call_app_tool("browser-use", "navigate", {})
        )
        await asyncio.wait_for(call_started.wait(), timeout=1.0)

        assert runner.active_tool_call_count == 1
        assert await manager._begin_liveness_probe(runner) is False

        finish_call.set()
        await call_task
        assert runner.active_tool_call_count == 0
```

- [ ] **Step 2: Run the failing activity-gate unit test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_liveness_probe_is_skipped_while_tool_call_is_active tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_app_bridge_tool_call_uses_activity_gate --no-cov -q
```

Expected: fail because `_TrackedMCPClientSession` and activity helpers do not exist.

- [ ] **Step 3: Add a call-tool session protocol in `tools.py`**

In `app/agent/mcp/tools.py`, update imports and the bottom session-provider alias so MCP tools depend only on the method they call:

```python
from typing import TYPE_CHECKING, Any, Protocol
```

Add:

```python
class _MCPCallSession(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        ...
```

Replace the bottom import/alias:

```python
from typing import Callable, Optional  # noqa: E402

_SessionProvider = Callable[[], Optional["_MCPCallSession"]]
```

Do not change `MCPTool._invoke()` behavior. This only widens the type from a concrete MCP SDK `ClientSession` to the minimum call surface used by the adapter.

- [ ] **Step 4: Add activity fields to `_ServerRunner`**

In `app/agent/mcp/manager.py`, add internal runtime fields:

```python
    activity_condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active_tool_call_count: int = 0
    liveness_probe_active: bool = False
```

These fields are internal only. Do not add them to `MCPServerStatus` or API schemas.

- [ ] **Step 5: Add tracked session wrapper**

Add this helper near `_ServerRunner`:

```python
class _TrackedMCPClientSession:
    def __init__(
        self,
        manager: MCPManager,
        runner: _ServerRunner,
        raw_session: object,
    ) -> None:
        self._manager = manager
        self._runner = runner
        self._raw_session = raw_session

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        await self._manager._begin_tool_call(self._runner)
        try:
            return await self._raw_session.call_tool(tool_name, arguments)
        finally:
            await self._manager._end_tool_call(self._runner)
```

Update `_ServerRunner.session` so it can hold the tracked wrapper:

```python
    session: "_TrackedMCPClientSession | None" = None
```

Keep the raw MCP SDK `ClientSession` object local to `_run_server_once()` and inside its async context. The runner should expose only the tracked wrapper to tool-call consumers.

- [ ] **Step 6: Add activity helper methods**

Add to `MCPManager`:

```python
    async def _begin_tool_call(self, runner: _ServerRunner) -> None:
        async with runner.activity_condition:
            while runner.liveness_probe_active:
                await runner.activity_condition.wait()
            runner.active_tool_call_count += 1

    async def _end_tool_call(self, runner: _ServerRunner) -> None:
        async with runner.activity_condition:
            runner.active_tool_call_count = max(0, runner.active_tool_call_count - 1)
            runner.activity_condition.notify_all()

    async def _begin_liveness_probe(self, runner: _ServerRunner) -> bool:
        async with runner.activity_condition:
            if runner.active_tool_call_count > 0:
                return False
            runner.liveness_probe_active = True
            return True

    async def _end_liveness_probe(self, runner: _ServerRunner) -> None:
        async with runner.activity_condition:
            runner.liveness_probe_active = False
            runner.activity_condition.notify_all()
```

This design does not serialize normal tool calls against each other. It only prevents liveness probes and tool calls from overlapping on the same session.

- [ ] **Step 7: Use tracked session for generated MCP tools and app bridge**

When `_run_server_once()` later creates the raw `ClientSession`, assign:

```python
                tracked_session = _TrackedMCPClientSession(self, runner, session)
                runner.session = tracked_session
```

Build `MCPTool(... session_provider=lambda r=runner: r.session)` exactly as today. `MCPTool._invoke()` and `MCPManager.call_app_tool()` will both go through `runner.session.call_tool()`, so both paths are tracked.

- [ ] **Step 8: Run activity-gate test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_liveness_probe_is_skipped_while_tool_call_is_active tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_app_bridge_tool_call_uses_activity_gate --no-cov -q
```

Expected: pass.

## Task 4: Watchdog Retry For Non-Auth Runtime Failures

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Test: `tests/agent/mcp/test_manager.py`

- [ ] **Step 1: Write failing watchdog retry test**

Add to `TestMCPRuntimeObservabilityStatus`:

```python
    @pytest.mark.asyncio
    async def test_watchdog_retries_non_auth_start_failure(self, monkeypatch) -> None:
        import app.agent.mcp.manager as mcp_manager_mod

        manager = MCPManager()
        attempts = 0

        class FakeStdioClient:
            async def __aenter__(self):
                return object(), object()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClientSession:
            def __init__(self, read, write):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def initialize(self):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("first boot failed")

            async def list_tools(self):
                return SimpleNamespace(tools=[])

        monkeypatch.setattr(mcp_manager_mod, "MCP_WATCHDOG_MAX_RETRIES", 2)
        monkeypatch.setattr(mcp_manager_mod, "MCP_RETRY_BASE_DELAY_SECONDS", 0.01)
        monkeypatch.setattr(mcp_manager_mod, "MCP_RETRY_MAX_DELAY_SECONDS", 0.01)

        with (
            patch("app.agent.mcp.manager.load_config") as mock_load,
            patch("mcp.client.stdio.stdio_client", return_value=FakeStdioClient()),
            patch("mcp.ClientSession", FakeClientSession),
        ):
            mock_load.return_value = MCPConfig(
                servers={"browser-use": StdioServerConfig(command="echo")}
            )

            await manager.start()
            runner = manager._runners["browser-use"]
            await asyncio.wait_for(runner.ready.wait(), timeout=1.0)

            status = manager.get_status("browser-use")
            assert status is not None
            assert status.state == "ready"
            assert status.auto_restart_count == 1
            assert status.last_restart_reason == "watchdog_retry"
            assert status.last_restart_at is not None
            assert status.last_failure_at is not None
            assert attempts == 2

            await manager.stop()
```

- [ ] **Step 2: Run the failing watchdog test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_watchdog_retries_non_auth_start_failure --no-cov -q
```

Expected: fail because current `_run_server()` does not retry.

- [ ] **Step 3: Add watchdog constants**

At module level in `app/agent/mcp/manager.py`:

```python
MCP_WATCHDOG_MAX_RETRIES = 5
MCP_FLAPPING_RESTART_THRESHOLD = 3
MCP_STABLE_WINDOW_SECONDS = 60.0
MCP_LIVENESS_INTERVAL_SECONDS = 5.0
MCP_RETRY_BASE_DELAY_SECONDS = 1.0
MCP_RETRY_MAX_DELAY_SECONDS = 30.0
```

- [ ] **Step 4: Add runtime observability helpers**

Add methods to `MCPManager`:

```python
    def _mark_failure(self, runner: _ServerRunner, exc: BaseException) -> None:
        runner.session = None
        runner.tools = []
        runner.status.state = "error"
        runner.status.error = _format_exception(exc)
        runner.status.tool_names = []
        runner.status.last_failure_at = self._now_iso()

    def _mark_watchdog_retry(self, status: MCPServerStatus) -> None:
        status.auto_restart_count += 1
        status.last_restart_reason = "watchdog_retry"
        status.last_restart_at = self._now_iso()
        status.state = "starting"

    @staticmethod
    def _retry_delay_seconds(retry_count: int) -> float:
        delay = MCP_RETRY_BASE_DELAY_SECONDS * (2 ** max(retry_count - 1, 0))
        return min(delay, MCP_RETRY_MAX_DELAY_SECONDS)
```

- [ ] **Step 5: Extract one-attempt connection helper**

Move the current transport/session body of `_run_server()` into `_run_server_once()` with this signature:

```python
    async def _run_server_once(
        self,
        name: str,
        server_cfg: StdioServerConfig | HttpServerConfig,
        runner: _ServerRunner,
        retry_count: int,
    ) -> int:
```

The helper should preserve current behavior: open transport, initialize, list tools, set `ready`, wait for shutdown, clear `runner.session` on shutdown. Liveness flapping reset is added in Task 5. Do not pass retry state through getter/setter callbacks; `_run_server()` owns the retry counter and passes the current integer into `_run_server_once()`.

- [ ] **Step 6: Replace `_run_server()` with retry loop**

Use this control structure:

```python
    async def _run_server(
        self,
        name: str,
        server_cfg: StdioServerConfig | HttpServerConfig,
        runner: _ServerRunner,
    ) -> None:
        retry_count = 0

        while not runner.shutdown.is_set():
            try:
                retry_count = await self._run_server_once(
                    name, server_cfg, runner, retry_count
                )
                return
            except asyncio.CancelledError:
                runner.status.state = "stopped"
                runner.status.error = None
                runner.ready.set()
                raise
            except OAuthRequiredError as exc:
                self._mark_auth_required(runner, str(exc))
                return
            except Exception as exc:
                if self._handle_auth_failure(name, server_cfg, runner, exc):
                    return
                logger.error(
                    "mcp_server_failed name={} transport={} err={}",
                    name,
                    server_cfg.transport,
                    exc,
                )
                self._mark_failure(runner, exc)
                retry_count += 1
                if retry_count > MCP_WATCHDOG_MAX_RETRIES:
                    runner.ready.set()
                    return
                self._mark_watchdog_retry(runner.status)
                delay = self._retry_delay_seconds(retry_count)
                try:
                    await asyncio.wait_for(runner.shutdown.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    continue
```

Extract current auth-required branches into `_mark_auth_required()` and `_handle_auth_failure()` so OAuth semantics stay exactly mapped.

The `_run_server_once()` return value is the retry count to keep after a normal shutdown path. In Task 4 it usually returns the input `retry_count`; Task 5 may return `0` after a stable liveness window clears flapping.

- [ ] **Step 7: Run watchdog retry test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_watchdog_retries_non_auth_start_failure --no-cov -q
```

Expected: pass.

## Task 5: Liveness Failure, Flapping, And Stable Reset

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Test: `tests/agent/mcp/test_manager.py`

- [ ] **Step 1: Write failing flapping test**

Add test:

```python
    @pytest.mark.asyncio
    async def test_watchdog_marks_flapping_after_retry_threshold(self, monkeypatch) -> None:
        import app.agent.mcp.manager as mcp_manager_mod

        manager = MCPManager()

        class FakeStdioClient:
            async def __aenter__(self):
                return object(), object()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FailingClientSession:
            def __init__(self, read, write):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def initialize(self):
                raise RuntimeError("always down")

        monkeypatch.setattr(mcp_manager_mod, "MCP_WATCHDOG_MAX_RETRIES", 3)
        monkeypatch.setattr(mcp_manager_mod, "MCP_FLAPPING_RESTART_THRESHOLD", 2)
        monkeypatch.setattr(mcp_manager_mod, "MCP_RETRY_BASE_DELAY_SECONDS", 0.01)
        monkeypatch.setattr(mcp_manager_mod, "MCP_RETRY_MAX_DELAY_SECONDS", 0.01)

        with (
            patch("app.agent.mcp.manager.load_config") as mock_load,
            patch("mcp.client.stdio.stdio_client", return_value=FakeStdioClient()),
            patch("mcp.ClientSession", FailingClientSession),
        ):
            mock_load.return_value = MCPConfig(
                servers={"browser-use": StdioServerConfig(command="echo")}
            )

            await manager.start()
            runner = manager._runners["browser-use"]
            await asyncio.wait_for(runner.ready.wait(), timeout=1.0)

            status = manager.get_status("browser-use")
            assert status is not None
            assert status.state == "error"
            assert status.auto_restart_count == 3
            assert status.flapping is True
            assert status.warning == "mcp_server_flapping"
```

- [ ] **Step 2: Run failing flapping test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_watchdog_marks_flapping_after_retry_threshold --no-cov -q
```

Expected: fail because flapping is not implemented.

- [ ] **Step 3: Add flapping helpers**

Add:

```python
    @staticmethod
    def _mark_flapping_if_needed(status: MCPServerStatus, retry_count: int) -> None:
        if retry_count >= MCP_FLAPPING_RESTART_THRESHOLD:
            status.flapping = True
            status.warning = "mcp_server_flapping"

    @staticmethod
    def _clear_flapping_after_stable_window(
        status: MCPServerStatus, started_at_loop: datetime, retry_count: int
    ) -> int:
        duration = (datetime.now(UTC) - started_at_loop).total_seconds()
        if duration <= MCP_STABLE_WINDOW_SECONDS:
            return retry_count
        status.flapping = False
        status.warning = None
        return 0
```

Call `_mark_flapping_if_needed(runner.status, retry_count)` after incrementing retry count and before checking retry cap.

- [ ] **Step 4: Add liveness monitor inside `_run_server_once()`**

After setting ready, create a liveness task and wait for shutdown or liveness failure. The liveness task must use the activity gate from Task 3:

```python
                started_at_loop = datetime.now(UTC)

                async def monitor_liveness() -> None:
                    nonlocal retry_count
                    while not runner.shutdown.is_set():
                        await asyncio.sleep(MCP_LIVENESS_INTERVAL_SECONDS)
                        should_probe = await self._begin_liveness_probe(runner)
                        if not should_probe:
                            continue
                        try:
                            await session.list_tools()
                            retry_count = self._clear_flapping_after_stable_window(
                                runner.status, started_at_loop, retry_count
                            )
                        except asyncio.CancelledError:
                            raise
                        finally:
                            await self._end_liveness_probe(runner)

                liveness_task = asyncio.create_task(
                    monitor_liveness(), name=f"mcp-liveness-{name}"
                )
                shutdown_task = asyncio.create_task(
                    runner.shutdown.wait(), name=f"mcp-shutdown-{name}"
                )
                done, pending = await asyncio.wait(
                    {liveness_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                if liveness_task in done:
                    await liveness_task
                return retry_count
```

This makes a failed `session.list_tools()` raise back into the watchdog loop only when no tool call is active during the probe. A normal shutdown exits without retry. `CancelledError` from the liveness task must propagate so shutdown/cancellation remains visible to the manager instead of being treated as an ordinary runtime failure.

- [ ] **Step 5: Run flapping test**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_watchdog_marks_flapping_after_retry_threshold --no-cov -q
```

Expected: pass.

- [ ] **Step 6: Write stable reset unit test**

Add a direct helper test:

```python
    def test_clear_flapping_after_stable_window(self, monkeypatch) -> None:
        import app.agent.mcp.manager as mcp_manager_mod

        status = MCPServerStatus(
            name="browser-use",
            transport="stdio",
            enabled=True,
            state="ready",
            flapping=True,
            warning="mcp_server_flapping",
        )
        started = mcp_manager_mod.datetime.now(mcp_manager_mod.UTC)
        monkeypatch.setattr(mcp_manager_mod, "MCP_STABLE_WINDOW_SECONDS", -1.0)

        retry_count = MCPManager._clear_flapping_after_stable_window(
            status, started, 4
        )

        assert retry_count == 0
        assert status.flapping is False
        assert status.warning is None
```

- [ ] **Step 7: Run Task 5 tests**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_watchdog_marks_flapping_after_retry_threshold tests/agent/mcp/test_manager.py::TestMCPRuntimeObservabilityStatus::test_clear_flapping_after_stable_window --no-cov -q
```

Expected: pass.

## Task 6: Preserve OAuth/Auth-Required Boundary

**Files:**
- Modify: `app/agent/mcp/manager.py`
- Test: `tests/agent/mcp/test_manager.py`

- [ ] **Step 1: Write auth boundary assertions**

Extend existing OAuth tests with observability assertions. For example in `test_oauth_server_without_tokens_is_auth_required`:

```python
            assert status.auto_restart_count == 0
            assert status.last_restart_reason is None
            assert status.last_restart_at is None
            assert status.flapping is False
            assert status.warning is None
```

Apply the same assertions to:

- `test_slack_without_oauth_config_is_auth_required`
- `test_http_missing_token_failure_without_oauth_config_is_auth_required`
- `test_oauth_registration_failure_is_auth_required`

- [ ] **Step 2: Run OAuth boundary tests**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py::TestMCPManagerOAuth::test_oauth_server_without_tokens_is_auth_required tests/agent/mcp/test_manager.py::TestMCPManagerOAuth::test_slack_without_oauth_config_is_auth_required tests/agent/mcp/test_manager.py::TestMCPManagerOAuth::test_http_missing_token_failure_without_oauth_config_is_auth_required tests/agent/mcp/test_manager.py::TestMCPManagerOAuth::test_oauth_registration_failure_is_auth_required --no-cov -q
```

Expected: pass. If any test fails, fix `_handle_auth_failure()` before continuing.

## Task 7: Regression And Snapshot

**Files:**
- Modify: `.agent/memory/CONTEXT_SNAPSHOT.md`

- [ ] **Step 1: Run targeted manager and route tests**

Run:

```powershell
uv run pytest tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py --no-cov -q
```

Expected: pass.

- [ ] **Step 2: Run neighboring route/service regression**

Run:

```powershell
uv run pytest tests/api/routes/test_observability_route.py tests/services/test_observability_service.py tests/agent/test_loader.py --no-cov -q
```

Expected: pass.

- [ ] **Step 3: Run lint and format checks**

Run:

```powershell
uv run ruff check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py
uv run ruff format --check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py
```

Expected: both pass.

- [ ] **Step 4: Run targeted type check**

Run:

```powershell
uv run ty check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py
```

Expected: pass for targeted files. If broad `ty check app/` still reports existing Windows/POSIX issues elsewhere, record that separately instead of treating it as this phase failing.

- [ ] **Step 5: Update context snapshot**

Update `.agent/memory/CONTEXT_SNAPSHOT.md`:

- mark MCP Runtime Observability Port v2 done if all targeted verification passes
- list verification commands and results
- remove or revise the old “not yet ported” next-step entry

- [ ] **Step 6: Commit**

Commit message:

```powershell
git add app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py .agent/memory/CONTEXT_SNAPSHOT.md
git commit -m "feat: port MCP runtime observability"
```

## Verification Commands

```powershell
uv run pytest tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py --no-cov -q
uv run pytest tests/api/routes/test_observability_route.py tests/services/test_observability_service.py tests/agent/test_loader.py --no-cov -q
uv run ruff check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py
uv run ruff format --check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py
uv run ty check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py
```

## Self-Review

- Spec coverage: The plan covers status fields, API projection, manual restart inheritance, active tool-call gating for liveness safety, watchdog retry, flapping detection/reset, OAuth exclusion, regression verification, and snapshot update.
- Scope check: No UI, persistence, metrics, new routes, permission changes, or MCP tool execution changes are included.
- Type consistency: Field names match the design doc and use the same names in dataclass, Pydantic schema, route projection, and tests.
- Ambiguity resolved: `reload_from_config()` does not preserve observability history in v2; only explicit `restart_server()` does.
