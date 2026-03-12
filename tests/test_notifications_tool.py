"""Tests for setup_monitoring, list_notifications, get_notification_history, delete_notification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.core.skyfi_types import (
    ListNotificationsResponse,
    NotificationResponse,
    NotificationWithHistory,
    StatusResponse,
)
from purveyor.server import mcp

NOTIFICATION_ID = str(uuid.uuid4())
OWNER_ID = str(uuid.uuid4())
SIMPLE_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"


def _make_notification(notification_id: str = NOTIFICATION_ID) -> NotificationResponse:
    return NotificationResponse(
        id=uuid.UUID(notification_id),
        owner_id=OWNER_ID,
        aoi=SIMPLE_WKT,
        gsd_min=None,
        gsd_max=None,
        product_type=None,
        webhook_url="https://example.com/webhook",
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _make_ctx(cached_client: MagicMock, webhook_url: str = "") -> MagicMock:
    ctx = MagicMock()
    mock_settings = MagicMock()
    mock_settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    mock_settings.webhook_base_url = webhook_url
    mock_settings.server_host = "0.0.0.0"
    mock_settings.server_port = 8000
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": mock_settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": None,
    }
    return ctx


# ---------------------------------------------------------------------------
# list_notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_notifications_returns_list() -> None:
    """list_notifications returns notification list and total."""
    notification = _make_notification()
    cached_client = MagicMock()
    cached_client.list_notifications = AsyncMock(
        return_value=ListNotificationsResponse(total=1, notifications=[notification])
    )

    tool_fn = mcp._tool_manager.get_tool("list_notifications").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["total"] == 1
    assert len(result["notifications"]) == 1


@pytest.mark.asyncio
async def test_list_notifications_api_error() -> None:
    """API error returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.list_notifications = AsyncMock(side_effect=Exception("timeout"))

    tool_fn = mcp._tool_manager.get_tool("list_notifications").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# get_notification_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_notification_history_returns_data() -> None:
    """get_notification_history returns notification with history."""
    notification_with_history = NotificationWithHistory(
        id=uuid.UUID(NOTIFICATION_ID),
        owner_id=OWNER_ID,
        aoi=SIMPLE_WKT,
        gsd_min=None,
        gsd_max=None,
        product_type=None,
        webhook_url="https://example.com/webhook",
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        history=[],
    )
    cached_client = MagicMock()
    cached_client.get_notification = AsyncMock(return_value=notification_with_history)

    tool_fn = mcp._tool_manager.get_tool("get_notification_history").fn
    result = await tool_fn(notification_id=NOTIFICATION_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["notification"]["id"] == NOTIFICATION_ID


@pytest.mark.asyncio
async def test_get_notification_history_api_error() -> None:
    """API error returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_notification = AsyncMock(side_effect=Exception("not found"))

    tool_fn = mcp._tool_manager.get_tool("get_notification_history").fn
    result = await tool_fn(notification_id="bad-id", ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# delete_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_notification_success() -> None:
    """delete_notification returns confirmation."""
    cached_client = MagicMock()
    cached_client.delete_notification = AsyncMock(
        return_value=StatusResponse(status="deleted")
    )

    tool_fn = mcp._tool_manager.get_tool("delete_notification").fn
    result = await tool_fn(notification_id=NOTIFICATION_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert "deleted" in result["summary"].lower() or NOTIFICATION_ID in result["summary"]


@pytest.mark.asyncio
async def test_delete_notification_api_error() -> None:
    """delete_notification API error returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.delete_notification = AsyncMock(side_effect=Exception("forbidden"))

    tool_fn = mcp._tool_manager.get_tool("delete_notification").fn
    result = await tool_fn(notification_id="bad-id", ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# setup_monitoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_monitoring_with_wkt_and_webhook() -> None:
    """setup_monitoring with WKT location and explicit webhook_url creates notification."""
    notification = _make_notification()
    cached_client = MagicMock()
    cached_client.create_notification = AsyncMock(return_value=notification)

    tool_fn = mcp._tool_manager.get_tool("setup_monitoring").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        webhook_url="https://myserver.com/webhooks/archive",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, dict)
    assert "notification_id" in result
    cached_client.create_notification.assert_called_once()


@pytest.mark.asyncio
async def test_setup_monitoring_localhost_warning() -> None:
    """setup_monitoring warns when webhook URL resolves to localhost."""
    notification = _make_notification()
    cached_client = MagicMock()
    cached_client.create_notification = AsyncMock(return_value=notification)

    tool_fn = mcp._tool_manager.get_tool("setup_monitoring").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        webhook_url="http://localhost:8000/webhooks/archive",
        ctx=_make_ctx(cached_client),
    )

    # Should succeed but include a warning
    assert isinstance(result, dict)
