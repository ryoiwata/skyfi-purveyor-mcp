"""Tests for list_orders, get_order_status, download_deliverable MCP tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.core.skyfi_types import (
    DeliveryStatus,
    ListOrdersResponse,
    OrderType,
    TaskingOrderResponse,
)
from purveyor.server import mcp

ORDER_ID = str(uuid.uuid4())
ARCHIVE_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
OWNER_ID = str(uuid.uuid4())


def _make_tasking_order(status: str = "CREATED") -> TaskingOrderResponse:
    return TaskingOrderResponse(
        id=uuid.uuid4(),
        order_id=ORDER_ID,
        item_id=ITEM_ID,
        order_type=OrderType.TASKING,
        order_cost=50_000,
        owner_id=OWNER_ID,
        status=(
            DeliveryStatus(status)
            if status in [s.value for s in DeliveryStatus]
            else DeliveryStatus.CREATED
        ),
        order_code="ORD-001",
        created_at=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
        aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        aoi_sqkm=12.3,
        window_start=datetime(2024, 7, 1, tzinfo=UTC),
        window_end=datetime(2024, 7, 31, tzinfo=UTC),
        product_type="DAY",
        resolution="VERY HIGH",
        download_image_url=None,
        download_payload_url=None,
    )


def _make_ctx(cached_client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": MagicMock(),
        "cache": MagicMock(),
        "session_factory": None,
    }
    return ctx


# ---------------------------------------------------------------------------
# list_orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orders_returns_orders() -> None:
    """list_orders returns order list with summary."""
    order = _make_tasking_order()
    cached_client = MagicMock()
    cached_client.list_orders = AsyncMock(
        return_value=ListOrdersResponse(total=1, orders=[order])
    )

    tool_fn = mcp._tool_manager.get_tool("list_orders").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["total"] == 1
    assert len(result["orders"]) == 1
    assert "1 total orders" in result["summary"]


@pytest.mark.asyncio
async def test_list_orders_invalid_type_returns_error() -> None:
    """Invalid order_type returns invalid_input error."""
    import json

    from mcp.types import CallToolResult

    cached_client = MagicMock()
    tool_fn = mcp._tool_manager.get_tool("list_orders").fn
    result = await tool_fn(order_type="INVALID_TYPE", ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_list_orders_api_error_returns_error() -> None:
    """API error returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.list_orders = AsyncMock(side_effect=Exception("timeout"))

    tool_fn = mcp._tool_manager.get_tool("list_orders").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


@pytest.mark.asyncio
async def test_list_orders_empty_returns_valid_result() -> None:
    """Empty order list returns valid (non-error) result."""
    cached_client = MagicMock()
    cached_client.list_orders = AsyncMock(
        return_value=ListOrdersResponse(total=0, orders=[])
    )

    tool_fn = mcp._tool_manager.get_tool("list_orders").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# get_order_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_returns_order() -> None:
    """get_order_status returns order details and summary."""
    order = _make_tasking_order("CREATED")
    cached_client = MagicMock()
    cached_client.get_order = AsyncMock(return_value=order)

    tool_fn = mcp._tool_manager.get_tool("get_order_status").fn
    result = await tool_fn(order_id=ORDER_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["status"] == "CREATED"
    assert ORDER_ID in result["summary"]


@pytest.mark.asyncio
async def test_get_order_status_completed_includes_urls() -> None:
    """Completed order includes download URLs dict (even if empty)."""
    order = _make_tasking_order("DELIVERY_COMPLETED")
    # Add download URLs
    order.download_image_url = "https://example.com/image.tif"
    order.download_payload_url = "https://example.com/payload.zip"

    cached_client = MagicMock()
    cached_client.get_order = AsyncMock(return_value=order)

    tool_fn = mcp._tool_manager.get_tool("get_order_status").fn
    result = await tool_fn(order_id=ORDER_ID, ctx=_make_ctx(cached_client))

    assert "download_urls" in result
    assert result["download_urls"].get("image") is not None


@pytest.mark.asyncio
async def test_get_order_status_api_error() -> None:
    """Failed fetch returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_order = AsyncMock(side_effect=Exception("404"))

    tool_fn = mcp._tool_manager.get_tool("get_order_status").fn
    result = await tool_fn(order_id="bad-id", ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# download_deliverable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_deliverable_returns_url() -> None:
    """download_deliverable returns signed URL."""
    download_url = "https://example.com/signed/image.tif?token=abc"
    cached_client = MagicMock()
    cached_client.get_deliverable_url = AsyncMock(return_value=download_url)

    tool_fn = mcp._tool_manager.get_tool("download_deliverable").fn
    result = await tool_fn(
        order_id=ORDER_ID,
        deliverable_type="image",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, dict)
    assert result["download_url"] == download_url
    assert result["order_id"] == ORDER_ID


@pytest.mark.asyncio
async def test_download_deliverable_invalid_type() -> None:
    """Invalid deliverable_type returns invalid_input error."""
    import json

    from mcp.types import CallToolResult

    cached_client = MagicMock()
    tool_fn = mcp._tool_manager.get_tool("download_deliverable").fn
    result = await tool_fn(
        order_id=ORDER_ID,
        deliverable_type="invalid_type",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_download_deliverable_api_error() -> None:
    """API error returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_deliverable_url = AsyncMock(side_effect=Exception("expired"))

    tool_fn = mcp._tool_manager.get_tool("download_deliverable").fn
    result = await tool_fn(
        order_id=ORDER_ID,
        deliverable_type="payload",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
