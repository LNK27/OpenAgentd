"""schedule_task tool — create, list, pause, resume, or delete scheduled tasks.

The agent can call this tool to manage the scheduler on behalf of the user,
e.g. "remind me every hour to check email" or "run the daily-report agent at 9 AM".

All operations proxy through the in-process :data:`~app.scheduler.scheduler.task_scheduler`
singleton so no HTTP round-trip is needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_task(task: Any) -> str:
    """Format a ScheduledTask (or ScheduledTaskResponse) into a readable line."""
    schedule = ""
    st = getattr(task, "schedule_type", "?")
    if st == "at":
        dt = getattr(task, "at_datetime", None)
        schedule = f"at {dt}" if dt else "at ?"
    elif st == "every":
        secs = getattr(task, "every_seconds", None)
        schedule = f"every {secs}s" if secs else "every ?"
    elif st == "cron":
        expr = getattr(task, "cron_expression", None)
        tz = getattr(task, "timezone", "UTC")
        schedule = f"cron '{expr}' ({tz})" if expr else "cron ?"

    status = getattr(task, "status", "unknown")
    enabled = getattr(task, "enabled", True)
    run_count = getattr(task, "run_count", 0)
    next_fire = getattr(task, "next_fire_at", None)
    name = getattr(task, "name", "?")
    mode = getattr(task, "mode", "normal")
    workspace = getattr(task, "workspace", None)
    task_id = getattr(task, "id", "?")

    target = f"mode={mode}"
    if mode == "coding" and workspace:
        target += f" workspace={workspace}"

    parts = [
        f"id={task_id}",
        f"name={name}",
        target,
        f"schedule={schedule}",
        f"status={'enabled' if enabled else 'paused'}/{status}",
        f"runs={run_count}",
    ]
    if next_fire:
        parts.append(f"next={next_fire}")
    return "  " + " | ".join(parts)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def _schedule_task(
    action: Annotated[
        Literal["create", "list", "pause", "resume", "delete", "trigger"],
        Field(
            description=(
                "Action to perform: "
                "'create' a new task, "
                "'list' all tasks, "
                "'pause' a running task, "
                "'resume' a paused task, "
                "'delete' a task, "
                "'trigger' a task immediately."
            )
        ),
    ],
    # ── create-only fields ──────────────────────────────────────────────────
    name: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[create] Unique task name. "
                "Pattern: ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$. "
                "Required for create."
            ),
        ),
    ] = None,
    schedule_type: Annotated[
        Literal["at", "every", "cron"] | None,
        Field(
            default=None,
            description=(
                "[create] Schedule type. Required for create. "
                "'at' = one-shot at a specific datetime, "
                "'every' = repeat every N seconds, "
                "'cron' = 5-field cron expression."
            ),
        ),
    ] = None,
    at_datetime: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[create, schedule_type='at'] ISO-8601 datetime string "
                "e.g. '2026-05-01T09:00:00+00:00'. Required when schedule_type='at'."
            ),
        ),
    ] = None,
    every_seconds: Annotated[
        int | None,
        Field(
            default=None,
            gt=0,
            description=(
                "[create, schedule_type='every'] Interval in seconds (> 0). "
                "Required when schedule_type='every'."
            ),
        ),
    ] = None,
    cron_expression: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[create, schedule_type='cron'] Standard 5-field cron expression "
                "e.g. '0 9 * * 1-5'. Required when schedule_type='cron'."
            ),
        ),
    ] = None,
    timezone: Annotated[
        str,
        Field(
            default="UTC",
            description=(
                "[create] IANA timezone name for cron/at interpretation, "
                "e.g. 'Asia/Ho_Chi_Minh', 'America/New_York'. Defaults to 'UTC'."
            ),
        ),
    ] = "UTC",
    prompt: Annotated[
        str | None,
        Field(
            default=None,
            description="[create] Message to send to the team lead when the task fires. Required for create.",
        ),
    ] = None,
    session_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[create] Session continuity. "
                "None = new session each fire, "
                "'auto' = persistent session keyed to the task name, "
                "UUID string = continue a specific existing session."
            ),
        ),
    ] = None,
    enabled: Annotated[
        bool,
        Field(
            default=True,
            description="[create] Whether the task starts enabled. Defaults to True.",
        ),
    ] = True,
    # ── pause / resume / delete / trigger fields ─────────────────────────────
    task_id: Annotated[
        str | None,
        Field(
            default=None,
            description="[pause|resume|delete|trigger] UUID of the task to act on.",
        ),
    ] = None,
    # ── injected ─────────────────────────────────────────────────────────────
    # ``_mode`` / ``_workspace`` are derived from the calling agent's runtime
    # context by the tool executor — never accepted from LLM-supplied args.
    # See ``app.agent.agent_loop.tool_executor.make_tool_executor``.
    _state: Annotated[Any, InjectedArg()] = None,
    _mode: Annotated[Literal["normal", "coding"], InjectedArg()] = "normal",
    _workspace: Annotated[str | None, InjectedArg()] = None,
) -> str:
    """Manage scheduled tasks: create recurring or one-shot agent prompts, list, pause, resume, delete, or trigger tasks.

    Use this when the user asks to automate something on a schedule —
    e.g. "check my email every hour", "run a report at 9 AM every weekday",
    "remind me tomorrow at 3 PM".
    """
    from app.scheduler.scheduler import task_scheduler

    # ── list ─────────────────────────────────────────────────────────────────
    if action == "list":
        tasks = await task_scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks."
        lines = [f"Scheduled tasks ({len(tasks)}):"]
        for t in tasks:
            lines.append(_fmt_task(t))
        return "\n".join(lines)

    # ── pause / resume / delete / trigger ────────────────────────────────────
    if action in ("pause", "resume", "delete", "trigger"):
        if not task_id:
            return f"Error: 'task_id' is required for action='{action}'."

        from uuid import UUID

        try:
            uid = UUID(task_id)
        except ValueError:
            return f"Error: '{task_id}' is not a valid UUID."

        if action == "pause":
            task = await task_scheduler.pause(uid)
            logger.info("schedule_tool_pause task_id={} name={}", uid, task.name)
            return f"Task '{task.name}' paused."

        if action == "resume":
            task = await task_scheduler.resume(uid)
            logger.info("schedule_tool_resume task_id={} name={}", uid, task.name)
            return f"Task '{task.name}' resumed. Next fire: {task.next_fire_at}"

        if action == "delete":
            # Fetch name before deleting for the confirmation message
            existing = await task_scheduler.get_task(uid)
            task_name = existing.name if existing else str(uid)
            await task_scheduler.remove(uid)
            logger.info("schedule_tool_delete task_id={} name={}", uid, task_name)
            return f"Task '{task_name}' deleted."

        if action == "trigger":
            existing = await task_scheduler.get_task(uid)
            if existing is None:
                return f"Error: no task with id '{task_id}'."
            await task_scheduler.trigger(uid)
            logger.info("schedule_tool_trigger task_id={} name={}", uid, existing.name)
            return f"Task '{existing.name}' triggered immediately."

    # ── create ───────────────────────────────────────────────────────────────
    if action == "create":
        missing = [
            f
            for f, v in [
                ("name", name),
                ("schedule_type", schedule_type),
                ("prompt", prompt),
            ]
            if not v
        ]
        if missing:
            return f"Error: the following fields are required for create: {', '.join(missing)}."
        # Narrow Optional → required for the type checker (the loop above
        # already guaranteed all three are truthy).
        assert name is not None
        assert schedule_type is not None
        assert prompt is not None

        from app.scheduler.models import ScheduledTask
        from app.scheduler.scheduler import task_scheduler as _scheduler
        from app.scheduler.schemas import ScheduledTaskCreate

        # Parse at_datetime string → datetime. If the string is naive (no
        # offset / "Z"), interpret it in the user-supplied `timezone` rather
        # than letting downstream code assume UTC.
        at_dt: datetime | None = None
        if at_datetime:
            try:
                at_dt = datetime.fromisoformat(at_datetime)
            except ValueError as exc:
                return f"Error: invalid at_datetime '{at_datetime}': {exc}"
            if at_dt.tzinfo is None:
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

                try:
                    at_dt = at_dt.replace(tzinfo=ZoneInfo(timezone))
                except ZoneInfoNotFoundError:
                    return f"Error: unknown timezone '{timezone}'."

        try:
            payload = ScheduledTaskCreate(
                name=name,
                mode=_mode,
                workspace=_workspace,
                schedule_type=schedule_type,
                at_datetime=at_dt,
                every_seconds=every_seconds,
                cron_expression=cron_expression,
                timezone=timezone,
                prompt=prompt,
                session_id=session_id,
                enabled=enabled,
            )
        except Exception as exc:
            return f"Error: invalid task configuration — {exc}"

        # Go through ``scheduler.create`` (not ``add``) so the workspace/
        # session compatibility validators run.
        try:
            created = await _scheduler.create(payload)
        except Exception as exc:
            return f"Error: failed to create task — {exc}"

        # ScheduledTask is only used implicitly via _scheduler.create; keep
        # the import for type narrowing in callers that consume `created`.
        _ = ScheduledTask

        logger.info(
            "schedule_tool_create name={} mode={} workspace={} schedule_type={} next_fire={}",
            created.name,
            created.mode,
            created.workspace,
            created.schedule_type,
            created.next_fire_at,
        )
        target_line = f"  mode        : {created.mode}\n" + (
            f"  workspace   : {created.workspace}\n" if created.workspace else ""
        )
        return (
            f"Scheduled task created.\n"
            f"  id          : {created.id}\n"
            f"  name        : {created.name}\n"
            + target_line
            + f"  schedule    : {created.schedule_type}\n"
            f"  next fire   : {created.next_fire_at}\n"
            f"  prompt      : {created.prompt!r}"
        )

    return f"Error: unknown action '{action}'."


schedule_task = Tool(
    _schedule_task,
    name="schedule_task",
)
