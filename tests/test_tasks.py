"""Tests for background task runner and startup recovery."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

from purveyor.core.tasks import recover_orphaned_tasks, run_background_task
from purveyor.models.tables import BackgroundTask

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory() -> Any:
    """In-memory SQLite session factory for task tests."""
    import purveyor.models.tables  # noqa: F401 — registers tables on Base.metadata
    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    sf = create_session_factory(engine)
    await init_db(engine)
    yield sf
    # Give background tasks a moment to finish before disposing the engine
    await asyncio.sleep(0.2)
    await engine.dispose()


# ---------------------------------------------------------------------------
# run_background_task
# ---------------------------------------------------------------------------


async def test_run_background_task_completes(session_factory: Any) -> None:
    """A task runs and transitions to 'completed' status."""
    completed = asyncio.Event()

    async def handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> dict[str, Any]:
        completed.set()
        return {"done": True, "input": payload.get("value")}

    task_id = await run_background_task(
        session_factory=session_factory,
        task_type="test_task",
        payload={"value": 42},
        handler=handler,
    )

    # Wait for handler to finish
    await asyncio.wait_for(completed.wait(), timeout=5.0)
    # Small extra wait for DB update
    await asyncio.sleep(0.05)

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)

    assert task is not None
    assert task.status == "completed"
    assert task.result is not None
    result = json.loads(task.result)
    assert result["done"] is True
    assert result["input"] == 42


async def test_run_background_task_failure(session_factory: Any) -> None:
    """When handler raises, task status becomes 'failed' and error is recorded."""
    failed = asyncio.Event()

    async def failing_handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> None:
        failed.set()
        raise ValueError("Something went wrong")

    task_id = await run_background_task(
        session_factory=session_factory,
        task_type="failing_task",
        payload={"key": "val"},
        handler=failing_handler,
    )

    await asyncio.wait_for(failed.wait(), timeout=5.0)
    await asyncio.sleep(0.05)

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)

    assert task is not None
    assert task.status == "failed"
    assert task.retry_count == 1
    assert task.result is not None
    result = json.loads(task.result)
    assert "Something went wrong" in result["error"]


async def test_run_background_task_creates_pending_record(session_factory: Any) -> None:
    """A BackgroundTask record is created with 'pending' status before handler runs."""
    started = asyncio.Event()
    allow_finish = asyncio.Event()

    async def slow_handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> None:
        started.set()
        await asyncio.wait_for(allow_finish.wait(), timeout=5.0)

    task_id = await run_background_task(
        session_factory=session_factory,
        task_type="slow_task",
        payload={},
        handler=slow_handler,
    )

    # Record is created immediately
    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)

    assert task is not None
    assert task.task_type == "slow_task"

    # Allow handler to finish
    allow_finish.set()
    await asyncio.wait_for(started.wait(), timeout=5.0)
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# recover_orphaned_tasks
# ---------------------------------------------------------------------------


async def test_recover_orphaned_tasks_reruns_pending(session_factory: Any) -> None:
    """recover_orphaned_tasks finds pending tasks and re-queues them."""
    recovered = asyncio.Event()

    async def recovery_handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> dict[str, Any]:
        recovered.set()
        return {"recovered": True}

    # Manually insert an orphaned 'pending' task
    async with session_factory() as session:
        orphaned = BackgroundTask(
            task_type="orphaned_task",
            payload=json.dumps({"orphan": True}),
            status="pending",
        )
        session.add(orphaned)
        await session.commit()
        await session.refresh(orphaned)
        orphaned_id = orphaned.id

    count = await recover_orphaned_tasks(
        session_factory=session_factory,
        handlers={"orphaned_task": recovery_handler},
    )

    assert count == 1

    await asyncio.wait_for(recovered.wait(), timeout=5.0)
    await asyncio.sleep(0.05)

    async with session_factory() as session:
        task = await session.get(BackgroundTask, orphaned_id)

    assert task is not None
    assert task.status == "completed"


async def test_recover_orphaned_tasks_skips_unknown_type(session_factory: Any) -> None:
    """recover_orphaned_tasks skips tasks with no registered handler."""
    async with session_factory() as session:
        task = BackgroundTask(
            task_type="unknown_type",
            payload=json.dumps({}),
            status="pending",
        )
        session.add(task)
        await session.commit()

    count = await recover_orphaned_tasks(
        session_factory=session_factory,
        handlers={},  # No handlers registered
    )

    # Found the task but couldn't handle it
    assert count == 0


async def test_recover_orphaned_tasks_ignores_completed(session_factory: Any) -> None:
    """recover_orphaned_tasks does not re-run completed tasks."""
    recovered = asyncio.Event()

    async def handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> None:
        recovered.set()

    async with session_factory() as session:
        task = BackgroundTask(
            task_type="done_task",
            payload=json.dumps({}),
            status="completed",
        )
        session.add(task)
        await session.commit()

    count = await recover_orphaned_tasks(
        session_factory=session_factory,
        handlers={"done_task": handler},
    )

    assert count == 0
    assert not recovered.is_set()


async def test_recover_orphaned_tasks_handles_running_state(session_factory: Any) -> None:
    """recover_orphaned_tasks also picks up 'running' tasks (crash recovery)."""
    recovered = asyncio.Event()

    async def handler(
        task_id: uuid.UUID, payload: dict[str, Any], session_factory: Any
    ) -> None:
        recovered.set()

    async with session_factory() as session:
        task = BackgroundTask(
            task_type="crashed_task",
            payload=json.dumps({}),
            status="running",  # Crashed mid-execution
        )
        session.add(task)
        await session.commit()

    count = await recover_orphaned_tasks(
        session_factory=session_factory,
        handlers={"crashed_task": handler},
    )

    assert count == 1
    await asyncio.wait_for(recovered.wait(), timeout=5.0)
