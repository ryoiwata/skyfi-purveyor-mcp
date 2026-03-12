"""Tests for create_tasking_order, create_archive_order, cancel_pending_order tools."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from purveyor.core.skyfi_types import (
    Archive,
    DeliveryStatus,
    OrderType,
    ProductType,
    TaskingOrderResponse,
)
from purveyor.server import mcp

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session_factory() -> Any:
    """In-memory SQLite session factory for tool tests."""
    import purveyor.models.tables  # noqa: F401 — registers tables on Base.metadata
    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    sf = create_session_factory(engine)
    await init_db(engine)
    yield sf
    await engine.dispose()


def _make_settings(session_factory: Any) -> MagicMock:
    from cryptography.fernet import Fernet

    settings = MagicMock()
    settings.skyfi_api_key = "test-api-key-123"
    settings.confirmation_base_url = "http://localhost:8000"
    settings.server_port = 8000
    settings.fernet_key = Fernet.generate_key()
    settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    return settings


def _make_ctx(
    cached_client: MagicMock,
    settings: MagicMock,
    session_factory: Any,
    cache: Any = None,
) -> MagicMock:
    if cache is None:
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": settings,
        "cache": cache,
        "session_factory": session_factory,
    }
    return ctx


def _make_tasking_order_response() -> TaskingOrderResponse:
    return TaskingOrderResponse(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        order_type=OrderType.TASKING,
        order_cost=42500,
        owner_id=uuid.uuid4(),
        status=DeliveryStatus.CREATED,
        order_code="TEST-001",
        created_at=datetime.now(UTC),
        aoi="POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
        aoi_sqkm=25.0,
        window_start=datetime.now(UTC),
        window_end=datetime.now(UTC),
        product_type="DAY",
        resolution="VERY HIGH",
    )


def _make_archive() -> Archive:
    return Archive(
        archiveId=str(uuid.uuid4()),
        provider="PLANET",
        constellation="PS",
        productType=ProductType.DAY,
        platformResolution=0.5,
        resolution="VERY HIGH",
        captureTimestamp=datetime.now(UTC),
        footprint="POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
        minSqKm=0.1,
        maxSqKm=500.0,
        priceForOneSquareKm=17.0,
        priceForOneSquareKmCents=1700,
        priceFullScene=425.0,
        totalAreaSquareKm=100.0,
        gsd=0.5,
    )


# ---------------------------------------------------------------------------
# create_tasking_order
# ---------------------------------------------------------------------------


async def test_create_tasking_order_returns_confirmation_url(
    db_session_factory: Any,
) -> None:
    """create_tasking_order returns confirmation_url and does NOT call SkyFi order endpoint."""

    settings = _make_settings(db_session_factory)
    cached_client = MagicMock()
    # Pricing call returns empty dict (no pricing match)
    cached_client.get_pricing = AsyncMock(return_value={})
    # Should NOT be called
    cached_client.create_tasking_order = AsyncMock()

    # Mock resolve_location to return WKT directly
    wkt = "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"
    mock_resolve = AsyncMock(return_value=(wkt, None))
    with patch("purveyor.tools.geospatial.resolve_location", new=mock_resolve):
        tool_fn = mcp._tool_manager.get_tool("create_tasking_order").fn
        result = await tool_fn(
            location=wkt,
            product_type="DAY",
            resolution="VERY HIGH",
            window_start="2026-03-15T10:00:00",
            window_end="2026-03-15T18:00:00",
            ctx=_make_ctx(cached_client, settings, db_session_factory),
        )

    # Should NOT have placed an actual order
    cached_client.create_tasking_order.assert_not_called()

    assert isinstance(result, dict)
    assert "confirmation_url" in result
    assert "http://localhost:8000/confirm/" in result["confirmation_url"]
    assert "confirmation_id" in result
    assert "estimated_cost_cents" in result
    assert "IMPORTANT" in result


async def test_create_tasking_order_invalid_window_date(db_session_factory: Any) -> None:
    """create_tasking_order with invalid date returns invalid_input error."""
    settings = _make_settings(db_session_factory)
    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(return_value={})

    wkt = "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"
    mock_resolve = AsyncMock(return_value=(wkt, None))
    with patch("purveyor.tools.geospatial.resolve_location", new=mock_resolve):
        tool_fn = mcp._tool_manager.get_tool("create_tasking_order").fn
        result = await tool_fn(
            location=wkt,
            product_type="DAY",
            resolution="VERY HIGH",
            window_start="not-a-date",
            window_end="2026-03-15T18:00:00",
            ctx=_make_ctx(cached_client, settings, db_session_factory),
        )

    from mcp.types import CallToolResult

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "invalid_input"


# ---------------------------------------------------------------------------
# create_archive_order
# ---------------------------------------------------------------------------


async def test_create_archive_order_returns_confirmation_url(
    db_session_factory: Any,
) -> None:
    """create_archive_order returns confirmation_url and does NOT call SkyFi order endpoint."""
    settings = _make_settings(db_session_factory)
    archive = _make_archive()

    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=archive)
    cached_client.create_archive_order = AsyncMock()  # Should NOT be called

    wkt = "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"

    tool_fn = mcp._tool_manager.get_tool("create_archive_order").fn
    result = await tool_fn(
        aoi=wkt,
        archive_id=archive.archive_id,
        ctx=_make_ctx(cached_client, settings, db_session_factory),
    )

    # Should NOT have placed an actual order
    cached_client.create_archive_order.assert_not_called()

    assert isinstance(result, dict)
    assert "confirmation_url" in result
    assert "http://localhost:8000/confirm/" in result["confirmation_url"]
    assert "confirmation_id" in result
    assert "IMPORTANT" in result


async def test_create_archive_order_archive_not_found(db_session_factory: Any) -> None:
    """create_archive_order when archive fetch fails returns error."""
    from mcp.types import CallToolResult

    settings = _make_settings(db_session_factory)
    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(side_effect=Exception("Archive not found"))

    wkt = "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"

    tool_fn = mcp._tool_manager.get_tool("create_archive_order").fn
    result = await tool_fn(
        aoi=wkt,
        archive_id="nonexistent-id",
        ctx=_make_ctx(cached_client, settings, db_session_factory),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# cancel_pending_order
# ---------------------------------------------------------------------------


async def test_cancel_pending_order_success(db_session_factory: Any) -> None:
    """cancel_pending_order cancels a pending confirmation successfully."""
    from cryptography.fernet import Fernet

    from purveyor.core.confirmation import create_confirmation, encrypt_confirmation_token

    key = Fernet.generate_key()
    token = encrypt_confirmation_token(
        {
            "api_key": "test-key",
            "order_type": "TASKING",
            "order_params": {},
            "estimated_cost_cents": 100,
        },
        key,
    )

    async with db_session_factory() as session:
        record = await create_confirmation(session, token, "TASKING", "a" * 64, 100)

    confirmation_id = str(record.id)
    settings = MagicMock()
    cached_client = MagicMock()

    tool_fn = mcp._tool_manager.get_tool("cancel_pending_order").fn
    result = await tool_fn(
        confirmation_id=confirmation_id,
        ctx=_make_ctx(cached_client, settings, db_session_factory),
    )

    assert isinstance(result, dict)
    assert result["status"] == "cancelled"
    assert confirmation_id in result["summary"]


async def test_cancel_pending_order_already_placed(db_session_factory: Any) -> None:
    """cancel_pending_order on a placed order returns isError=True."""
    from cryptography.fernet import Fernet
    from mcp.types import CallToolResult

    from purveyor.core.confirmation import create_confirmation, encrypt_confirmation_token

    key = Fernet.generate_key()
    token = encrypt_confirmation_token(
        {"api_key": "k", "order_type": "TASKING", "order_params": {}, "estimated_cost_cents": 0},
        key,
    )

    async with db_session_factory() as session:
        record = await create_confirmation(session, token, "TASKING", "b" * 64, 0)
        record.status = "placed"
        await session.commit()
        record_id = record.id

    settings = MagicMock()
    cached_client = MagicMock()

    tool_fn = mcp._tool_manager.get_tool("cancel_pending_order").fn
    result = await tool_fn(
        confirmation_id=str(record_id),
        ctx=_make_ctx(cached_client, settings, db_session_factory),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "order_already_placed"


async def test_cancel_pending_order_invalid_uuid(db_session_factory: Any) -> None:
    """cancel_pending_order with invalid UUID returns invalid_input error."""
    from mcp.types import CallToolResult

    settings = MagicMock()
    cached_client = MagicMock()

    tool_fn = mcp._tool_manager.get_tool("cancel_pending_order").fn
    result = await tool_fn(
        confirmation_id="not-a-uuid",
        ctx=_make_ctx(cached_client, settings, db_session_factory),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "invalid_input"
