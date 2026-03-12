"""Tests for database engine creation, table creation, and basic CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from purveyor.models.database import create_engine, create_session_factory, init_db
from purveyor.models.tables import (
    BackgroundTask,
    GeocodeCache,
    NotificationRegistry,
    OrderConfirmation,
    WebhookEvent,
)


@pytest.fixture
async def memory_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(memory_engine):
    """Create a database session for testing."""
    factory = create_session_factory(memory_engine)
    async with factory() as sess:
        yield sess


class TestEngineCreation:
    """Tests for create_engine factory."""

    async def test_sqlite_engine_created(self) -> None:
        """SQLite engine is created without errors."""
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        assert engine is not None
        await engine.dispose()

    async def test_sqlite_in_memory_connection(self) -> None:
        """In-memory SQLite engine accepts connections."""
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1
        await engine.dispose()


class TestTableCreation:
    """Tests for init_db table creation."""

    async def test_tables_created(self, memory_engine) -> None:
        """All expected tables are created."""
        async with memory_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = {row[0] for row in result.fetchall()}

        expected = {
            "order_confirmations",
            "webhook_events",
            "background_tasks",
            "notification_registry",
            "geocode_cache",
            "alembic_version",  # may or may not exist depending on method
        }
        # Verify core tables exist
        for table in expected - {"alembic_version"}:
            assert table in tables, f"Table {table!r} not found in {tables}"


class TestOrderConfirmationCRUD:
    """Tests for OrderConfirmation model CRUD operations."""

    async def test_create_order_confirmation(self, session: AsyncSession) -> None:
        """Create and retrieve an OrderConfirmation record."""
        now = datetime.now(tz=timezone.utc)
        expires = now + timedelta(minutes=30)

        record = OrderConfirmation(
            token_hash="a" * 64,
            status="pending",
            order_type="ARCHIVE",
            api_key_hash="b" * 64,
            expires_at=expires,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        assert record.id is not None
        assert record.status == "pending"
        assert record.order_type == "ARCHIVE"
        assert record.created_at is not None

    async def test_update_order_status(self, session: AsyncSession) -> None:
        """Update an OrderConfirmation status to placed."""
        now = datetime.now(tz=timezone.utc)
        record = OrderConfirmation(
            token_hash="c" * 64,
            status="pending",
            order_type="TASKING",
            api_key_hash="d" * 64,
            expires_at=now + timedelta(minutes=30),
        )
        session.add(record)
        await session.commit()

        record.status = "placed"
        record.skyfi_order_id = uuid.uuid4()
        record.confirmed_at = now
        await session.commit()
        await session.refresh(record)

        assert record.status == "placed"
        assert record.skyfi_order_id is not None


class TestWebhookEventCRUD:
    """Tests for WebhookEvent model."""

    async def test_create_webhook_event(self, session: AsyncSession) -> None:
        """Create a webhook event record."""
        event = WebhookEvent(
            event_type="order_status",
            payload='{"order_id": "abc"}',
            api_key_hash="e" * 64,
            delivered=False,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        assert event.id is not None
        assert event.delivered is False
        assert event.event_type == "order_status"

    async def test_mark_event_delivered(self, session: AsyncSession) -> None:
        """Mark a webhook event as delivered."""
        event = WebhookEvent(
            event_type="archive_notification",
            payload='{"archive_id": "xyz"}',
            delivered=False,
        )
        session.add(event)
        await session.commit()

        event.delivered = True
        await session.commit()
        await session.refresh(event)

        assert event.delivered is True


class TestNotificationRegistry:
    """Tests for NotificationRegistry model."""

    async def test_create_registry_entry(self, session: AsyncSession) -> None:
        """Create a notification registry mapping."""
        notification_id = uuid.uuid4()
        entry = NotificationRegistry(
            id=notification_id,
            api_key_hash="f" * 64,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

        assert entry.id == notification_id
        assert entry.api_key_hash == "f" * 64
