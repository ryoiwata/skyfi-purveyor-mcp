"""Background task runner with startup recovery and idempotency.

Per DESIGN_DECISIONS §8: background tasks must be idempotent. Status transitions
tracked in the background_tasks table ensure recovery after restart.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import select

from purveyor.models.tables import BackgroundTask

log = structlog.get_logger(__name__)


async def run_background_task(
    session_factory: Any,
    task_type: str,
    payload: dict[str, Any],
    handler: Callable[..., Coroutine[Any, Any, Any]],
    background_tasks: BackgroundTasks | None = None,
) -> uuid.UUID:
    """Create and schedule a background task.

    Creates a BackgroundTask record in DB, then runs the handler asynchronously.
    Status transitions: pending → running → completed/failed.

    Args:
        session_factory: SQLAlchemy async session factory.
        task_type: Task type string (e.g., "poll_order_confirmation").
        payload: JSON-serializable task parameters.
        handler: Async callable that accepts (task_id, payload, session_factory).
        background_tasks: Optional FastAPI BackgroundTasks for scheduling.

    Returns:
        The UUID of the created BackgroundTask record.
    """
    async with session_factory() as session:
        task = BackgroundTask(
            task_type=task_type,
            payload=json.dumps(payload),
            status="pending",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    log.info("background_task_created", task_id=str(task_id), task_type=task_type)

    async def _run() -> None:
        await _execute_task(session_factory, task_id, payload, handler)

    if background_tasks is not None:
        background_tasks.add_task(_run)
    else:
        # Store the task reference to prevent premature garbage collection
        _task = asyncio.create_task(_run())
        _task.add_done_callback(lambda _: None)  # suppress warning

    return task_id


async def _execute_task(
    session_factory: Any,
    task_id: uuid.UUID,
    payload: dict[str, Any],
    handler: Callable[..., Coroutine[Any, Any, Any]],
) -> None:
    """Internal: run the handler and update task status."""
    # Mark running
    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        if task is None:
            log.error("background_task_not_found", task_id=str(task_id))
            return
        task.status = "running"
        task.started_at = datetime.now(UTC)
        await session.commit()

    try:
        result = await handler(task_id=task_id, payload=payload, session_factory=session_factory)
        async with session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            if task is not None:
                task.status = "completed"
                task.completed_at = datetime.now(UTC)
                task.result = json.dumps(result) if result is not None else None
                await session.commit()
        log.info("background_task_completed", task_id=str(task_id))
    except Exception as exc:
        log.error("background_task_failed", task_id=str(task_id), error=str(exc))
        async with session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            if task is not None:
                task.status = "failed"
                task.completed_at = datetime.now(UTC)
                task.result = json.dumps({"error": str(exc)})
                task.retry_count += 1
                await session.commit()


async def recover_orphaned_tasks(
    session_factory: Any,
    handlers: dict[str, Callable[..., Coroutine[Any, Any, Any]]],
    use_skip_locked: bool = False,
) -> int:
    """On startup, find and re-queue orphaned tasks.

    Queries BackgroundTask WHERE status IN ('pending', 'running') and
    re-runs each via the provided handlers dict.

    Per DESIGN_DECISIONS §8: tasks must be idempotent — safe to run multiple times.
    Per DESIGN_DECISIONS §10: use SELECT FOR UPDATE SKIP LOCKED on Postgres,
    simple SELECT on SQLite.

    Args:
        session_factory: SQLAlchemy async session factory.
        handlers: Dict mapping task_type strings to handler callables.
        use_skip_locked: If True, use SELECT FOR UPDATE SKIP LOCKED (Postgres).

    Returns:
        Number of tasks recovered.
    """
    async with session_factory() as session:
        stmt = select(BackgroundTask).where(
            BackgroundTask.status.in_(["pending", "running"])
        )
        if use_skip_locked:
            stmt = stmt.with_for_update(skip_locked=True)
        result = await session.execute(stmt)
        orphaned = list(result.scalars().all())

    count = 0
    for task in orphaned:
        handler = handlers.get(task.task_type)
        if handler is None:
            log.warning("no_handler_for_task_type", task_type=task.task_type)
            continue
        payload = json.loads(task.payload)
        _t = asyncio.create_task(
            _execute_task(session_factory, task.id, payload, handler)
        )
        _t.add_done_callback(lambda _: None)  # suppress warning
        count += 1

    if count:
        log.info("recovered_orphaned_tasks", count=count)

    return count
