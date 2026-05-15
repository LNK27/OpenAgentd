"""Tests for app/agent/tools/builtin/schedule.py — schedule_task tool."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid7

import pytest

from app.agent.tools.builtin.schedule import schedule_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_task_scheduler():
    """Mock the task_scheduler singleton."""
    return AsyncMock()


@pytest.fixture
def sample_task():
    """Create a sample ScheduledTask-like object for testing."""
    task = MagicMock()
    task.id = uuid7()
    task.name = "test-task"
    task.mode = "normal"
    task.workspace = None
    task.schedule_type = "every"
    task.every_seconds = 3600
    task.at_datetime = None
    task.cron_expression = None
    task.timezone = "UTC"
    task.prompt = "Check email"
    task.session_id = None
    task.enabled = True
    task.status = "pending"
    task.run_count = 0
    task.next_fire_at = datetime.now(timezone.utc)
    return task


# Reusable ``_injected`` payloads — production runs receive these from the
# tool executor; tests pass them in directly via ``Tool.arun``.
_NORMAL_INJECTED = {"_mode": "normal", "_workspace": None}


def _coding_injected(workspace: str) -> dict[str, object]:
    return {"_mode": "coding", "_workspace": workspace}


# ---------------------------------------------------------------------------
# Action: list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_no_tasks(mock_task_scheduler):
    """Returns 'No scheduled tasks.' when scheduler returns empty list."""
    mock_task_scheduler.list_tasks.return_value = []

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="list")

    assert result == "No scheduled tasks."
    mock_task_scheduler.list_tasks.assert_called_once()


@pytest.mark.asyncio
async def test_list_single_task(mock_task_scheduler, sample_task, clean_db):
    """Returns formatted task line for a single task."""
    mock_task_scheduler.list_tasks.return_value = [sample_task]

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="list")

    assert "Scheduled tasks (1):" in result
    assert f"id={sample_task.id}" in result
    assert "name=test-task" in result
    assert "mode=normal" in result
    assert "schedule=every 3600s" in result
    assert "status=enabled/pending" in result
    assert "runs=0" in result


@pytest.mark.asyncio
async def test_list_includes_workspace_for_coding(mock_task_scheduler, sample_task):
    """Coding tasks render workspace in the listing line."""
    sample_task.mode = "coding"
    sample_task.workspace = "/tmp/project"
    mock_task_scheduler.list_tasks.return_value = [sample_task]

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="list")

    assert "mode=coding workspace=/tmp/project" in result


@pytest.mark.asyncio
async def test_list_task_with_at_schedule(mock_task_scheduler):
    """Formats 'at' schedule type correctly."""
    task = MagicMock()
    task.id = uuid7()
    task.name = "one-shot"
    task.mode = "normal"
    task.workspace = None
    task.schedule_type = "at"
    task.at_datetime = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    task.every_seconds = None
    task.cron_expression = None
    task.timezone = "UTC"
    task.prompt = "Run once"
    task.session_id = None
    task.enabled = True
    task.status = "pending"
    task.run_count = 0
    task.next_fire_at = task.at_datetime

    mock_task_scheduler.list_tasks.return_value = [task]

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="list")

    assert "at 2026-05-01 09:00:00+00:00" in result


# ---------------------------------------------------------------------------
# Action: create — validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_missing_name(mock_task_scheduler):
    """Returns error when name is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "name" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_create_missing_schedule_type(mock_task_scheduler):
    """Returns error when schedule_type is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            prompt="Check email",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "schedule_type" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_create_missing_prompt(mock_task_scheduler):
    """Returns error when prompt is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "prompt" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_create_invalid_at_datetime_format(mock_task_scheduler):
    """Returns error for invalid at_datetime format."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="at",
            at_datetime="not-a-datetime",
            prompt="Run once",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "at_datetime" in result
    assert "invalid" in result


@pytest.mark.asyncio
async def test_create_invalid_schedule_type(mock_task_scheduler):
    """Raises ToolArgumentError for invalid schedule_type value."""
    from app.agent.errors import ToolArgumentError

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        with pytest.raises(ToolArgumentError):
            await schedule_task.arun(
                action="create",
                name="test-task",
                schedule_type="weekly",  # Invalid
                prompt="Run weekly",
                _injected=_NORMAL_INJECTED,
            )


@pytest.mark.asyncio
async def test_create_invalid_cron_expression(mock_task_scheduler):
    """Returns error for invalid cron expression."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="cron",
            cron_expression="not-a-cron",
            prompt="Run on schedule",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "invalid task configuration" in result


# ---------------------------------------------------------------------------
# Action: create — successful cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_every_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully creates an 'every' task with mode auto-injected as 'normal'."""
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    assert f"id          : {sample_task.id}" in result
    assert "name        : test-task" in result
    assert "mode        : normal" in result
    assert "schedule    : every" in result
    assert "prompt      : 'Check email'" in result
    mock_task_scheduler.create.assert_called_once()
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.mode == "normal"
    assert payload.workspace is None


@pytest.mark.asyncio
async def test_create_in_coding_context_auto_injects_workspace(
    mock_task_scheduler, sample_task, clean_db
):
    """When the calling agent runs in a coding team, the task inherits
    ``mode='coding'`` and the team's workspace — no LLM-supplied value."""
    sample_task.mode = "coding"
    sample_task.workspace = "/tmp/project"
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            _injected=_coding_injected("/tmp/project"),
        )

    assert "Scheduled task created." in result
    assert "mode        : coding" in result
    assert "workspace   : /tmp/project" in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.mode == "coding"
    assert payload.workspace == "/tmp/project"


@pytest.mark.asyncio
async def test_create_at_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully creates an 'at' task with ISO datetime string."""
    sample_task.schedule_type = "at"
    sample_task.at_datetime = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    sample_task.every_seconds = None
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="at",
            at_datetime="2026-05-01T09:00:00+00:00",
            prompt="Run once",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    assert "schedule    : at" in result
    mock_task_scheduler.create.assert_called_once()
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.at_datetime == datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_create_at_naive_string_uses_supplied_timezone(
    mock_task_scheduler, sample_task, clean_db
):
    """A naive ISO string for ``at_datetime`` must be interpreted in the
    user-supplied ``timezone``, not silently treated as UTC."""
    from zoneinfo import ZoneInfo

    sample_task.schedule_type = "at"
    sample_task.every_seconds = None
    expected = datetime(2026, 5, 10, 1, 12, 42, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    sample_task.at_datetime = expected
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="at",
            at_datetime="2026-05-10T01:12:42",  # naive — no offset
            timezone="Asia/Ho_Chi_Minh",
            prompt="Run once",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.at_datetime is not None
    assert payload.at_datetime.tzinfo is not None
    assert payload.at_datetime == expected
    assert payload.at_datetime.astimezone(timezone.utc) == datetime(
        2026, 5, 9, 18, 12, 42, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_create_at_aware_string_passthrough(
    mock_task_scheduler, sample_task, clean_db
):
    """An ISO string that already carries an offset is left untouched."""
    sample_task.schedule_type = "at"
    sample_task.every_seconds = None
    sample_task.at_datetime = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="at",
            at_datetime="2026-05-01T09:00:00+00:00",
            timezone="Asia/Ho_Chi_Minh",
            prompt="Run once",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.at_datetime == datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_create_at_unknown_timezone_returns_error(
    mock_task_scheduler, sample_task, clean_db
):
    """A naive datetime + unknown IANA zone must surface a clear error."""
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="at",
            at_datetime="2026-05-10T01:12:42",
            timezone="Mars/Olympus_Mons",
            prompt="Run once",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error" in result
    assert "Mars/Olympus_Mons" in result
    mock_task_scheduler.create.assert_not_called()


@pytest.mark.asyncio
async def test_create_cron_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully creates a 'cron' task."""
    sample_task.schedule_type = "cron"
    sample_task.cron_expression = "0 9 * * 1-5"
    sample_task.timezone = "America/New_York"
    sample_task.every_seconds = None
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="cron",
            cron_expression="0 9 * * 1-5",
            timezone="America/New_York",
            prompt="Daily report",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    assert "schedule    : cron" in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.cron_expression == "0 9 * * 1-5"
    assert payload.timezone == "America/New_York"


@pytest.mark.asyncio
async def test_create_with_session_id_auto(mock_task_scheduler, sample_task, clean_db):
    """Creates task with session_id='auto'."""
    sample_task.session_id = "auto"
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            session_id="auto",
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.session_id == "auto"


@pytest.mark.asyncio
async def test_create_with_session_id_uuid(mock_task_scheduler, sample_task, clean_db):
    """Creates task with a specific session UUID."""
    session_uuid = str(uuid7())
    sample_task.session_id = session_uuid
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            session_id=session_uuid,
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.session_id == session_uuid


@pytest.mark.asyncio
async def test_create_with_enabled_false(mock_task_scheduler, sample_task, clean_db):
    """Creates a disabled task."""
    sample_task.enabled = False
    mock_task_scheduler.create.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            enabled=False,
            _injected=_NORMAL_INJECTED,
        )

    assert "Scheduled task created." in result
    payload = mock_task_scheduler.create.call_args[0][0]
    assert payload.enabled is False


@pytest.mark.asyncio
async def test_create_scheduler_create_raises(mock_task_scheduler):
    """Returns error string when ``scheduler.create`` raises."""
    mock_task_scheduler.create.side_effect = RuntimeError("Database error")

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(
            action="create",
            name="test-task",
            schedule_type="every",
            every_seconds=3600,
            prompt="Check email",
            _injected=_NORMAL_INJECTED,
        )

    assert "Error:" in result
    assert "failed to create task" in result
    assert "Database error" in result


# ---------------------------------------------------------------------------
# Action: pause
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_missing_task_id(mock_task_scheduler):
    """Returns error when task_id is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="pause")

    assert "Error:" in result
    assert "task_id" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_pause_invalid_uuid(mock_task_scheduler):
    """Returns error when task_id is not a valid UUID."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="pause", task_id="not-a-uuid")

    assert "Error:" in result
    assert "not a valid UUID" in result


@pytest.mark.asyncio
async def test_pause_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully pauses a task."""
    task_id = str(sample_task.id)
    mock_task_scheduler.pause.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="pause", task_id=task_id)

    assert "Task 'test-task' paused." in result
    mock_task_scheduler.pause.assert_called_once_with(sample_task.id)


@pytest.mark.asyncio
async def test_pause_scheduler_raises(mock_task_scheduler):
    """Raises ToolExecutionError when task_scheduler.pause() raises."""
    from app.agent.errors import ToolExecutionError

    task_id = str(uuid7())
    mock_task_scheduler.pause.side_effect = RuntimeError("Task not found")

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        with pytest.raises(ToolExecutionError):
            await schedule_task.arun(action="pause", task_id=task_id)


# ---------------------------------------------------------------------------
# Action: resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_missing_task_id(mock_task_scheduler):
    """Returns error when task_id is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="resume")

    assert "Error:" in result
    assert "task_id" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_resume_invalid_uuid(mock_task_scheduler):
    """Returns error when task_id is not a valid UUID."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="resume", task_id="not-a-uuid")

    assert "Error:" in result
    assert "not a valid UUID" in result


@pytest.mark.asyncio
async def test_resume_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully resumes a task."""
    task_id = str(sample_task.id)
    next_fire = datetime.now(timezone.utc)
    sample_task.next_fire_at = next_fire
    mock_task_scheduler.resume.return_value = sample_task

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="resume", task_id=task_id)

    assert "Task 'test-task' resumed." in result
    assert f"Next fire: {next_fire}" in result
    mock_task_scheduler.resume.assert_called_once_with(sample_task.id)


@pytest.mark.asyncio
async def test_resume_scheduler_raises(mock_task_scheduler):
    """Raises ToolExecutionError when task_scheduler.resume() raises."""
    from app.agent.errors import ToolExecutionError

    task_id = str(uuid7())
    mock_task_scheduler.resume.side_effect = RuntimeError("Task not found")

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        with pytest.raises(ToolExecutionError):
            await schedule_task.arun(action="resume", task_id=task_id)


# ---------------------------------------------------------------------------
# Action: delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_missing_task_id(mock_task_scheduler):
    """Returns error when task_id is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="delete")

    assert "Error:" in result
    assert "task_id" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_delete_invalid_uuid(mock_task_scheduler):
    """Returns error when task_id is not a valid UUID."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="delete", task_id="not-a-uuid")

    assert "Error:" in result
    assert "not a valid UUID" in result


@pytest.mark.asyncio
async def test_delete_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully deletes a task."""
    task_id = str(sample_task.id)
    mock_task_scheduler.get_task.return_value = sample_task
    mock_task_scheduler.remove.return_value = None

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="delete", task_id=task_id)

    assert "Task 'test-task' deleted." in result
    mock_task_scheduler.get_task.assert_called_once_with(sample_task.id)
    mock_task_scheduler.remove.assert_called_once_with(sample_task.id)


@pytest.mark.asyncio
async def test_delete_task_not_found_uses_uuid_as_fallback(mock_task_scheduler):
    """When task not found, still calls remove and uses UUID as fallback name."""
    task_id = str(uuid7())
    mock_task_scheduler.get_task.return_value = None
    mock_task_scheduler.remove.return_value = None

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="delete", task_id=task_id)

    assert "Task '" in result
    assert "deleted." in result
    assert task_id in result
    mock_task_scheduler.get_task.assert_called_once()
    mock_task_scheduler.remove.assert_called_once()


# ---------------------------------------------------------------------------
# Action: trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_missing_task_id(mock_task_scheduler):
    """Returns error when task_id is missing."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="trigger")

    assert "Error:" in result
    assert "task_id" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_trigger_invalid_uuid(mock_task_scheduler):
    """Returns error when task_id is not a valid UUID."""
    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="trigger", task_id="not-a-uuid")

    assert "Error:" in result
    assert "not a valid UUID" in result


@pytest.mark.asyncio
async def test_trigger_task_not_found(mock_task_scheduler):
    """Returns error when task not found."""
    task_id = str(uuid7())
    mock_task_scheduler.get_task.return_value = None

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="trigger", task_id=task_id)

    assert "Error:" in result
    assert "no task with id" in result


@pytest.mark.asyncio
async def test_trigger_success(mock_task_scheduler, sample_task, clean_db):
    """Successfully triggers a task."""
    task_id = str(sample_task.id)
    mock_task_scheduler.get_task.return_value = sample_task
    mock_task_scheduler.trigger.return_value = None

    with patch("app.scheduler.scheduler.task_scheduler", mock_task_scheduler):
        result = await schedule_task.arun(action="trigger", task_id=task_id)

    assert "Task 'test-task' triggered immediately." in result
    mock_task_scheduler.trigger.assert_called_once_with(sample_task.id)


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_schedule_task_tool_name(clean_db):
    """Verify tool name is correct."""
    assert schedule_task.name == "schedule_task"


def test_schedule_task_tool_has_description(clean_db):
    """Verify tool has a description."""
    assert schedule_task.description
    assert "schedule" in schedule_task.description.lower()


def test_schedule_task_tool_definition(clean_db):
    """Verify tool definition is properly formatted."""
    definition = schedule_task.definition
    assert definition["type"] == "function"
    assert definition["function"]["name"] == "schedule_task"
    params = definition["function"]["parameters"]["properties"]
    assert "action" in params
    # mode + workspace are derived from runtime context, not exposed to the LLM.
    assert "mode" not in params
    assert "workspace" not in params


# ---------------------------------------------------------------------------
# Loader auto-injection tests
# ---------------------------------------------------------------------------


def test_build_agent_injects_schedule_task_for_lead(clean_db):
    """_build_agent auto-injects schedule_task for role='lead' agents."""
    from unittest.mock import MagicMock
    from app.agent.loader import AgentConfig, _build_agent

    factory = MagicMock()
    factory.return_value = MagicMock()

    cfg = AgentConfig(name="lead-agent", role="lead", system_prompt="Lead prompt")
    agent = _build_agent(cfg, {}, factory)

    assert "schedule_task" in agent._tools
    tool = agent._tools["schedule_task"]
    assert tool.name == "schedule_task"


def test_build_agent_does_not_inject_schedule_task_for_member(clean_db):
    """_build_agent does NOT inject schedule_task for role='member' agents."""
    from unittest.mock import MagicMock
    from app.agent.loader import AgentConfig, _build_agent

    factory = MagicMock()
    factory.return_value = MagicMock()

    cfg = AgentConfig(name="member-agent", role="member", system_prompt="Member prompt")
    agent = _build_agent(cfg, {}, factory)

    assert "schedule_task" not in agent._tools


def test_build_agent_schedule_task_not_duplicated(clean_db):
    """If schedule_task is listed in cfg.tools, it is not duplicated."""
    from unittest.mock import MagicMock
    from app.agent.loader import AgentConfig, _build_agent

    factory = MagicMock()
    factory.return_value = MagicMock()

    cfg = AgentConfig(
        name="lead-agent",
        role="lead",
        system_prompt="Lead prompt",
        tools=["schedule_task"],
    )
    agent = _build_agent(cfg, {}, factory)

    assert list(agent._tools.keys()).count("schedule_task") == 1
