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
async def test_get_order_status_completed_includes_api_endpoints() -> None:
    """Completed order includes api_download_endpoints (renamed from download_urls).

    api_download_endpoints contains Platform API paths that require auth headers;
    agents should use download_deliverable to get a signed URL instead.
    """
    order = _make_tasking_order("DELIVERY_COMPLETED")
    order.download_image_url = "https://app.skyfi.com/platform-api/orders/abc/image"
    order.download_payload_url = "https://app.skyfi.com/platform-api/orders/abc/payload"

    cached_client = MagicMock()
    cached_client.get_order = AsyncMock(return_value=order)

    tool_fn = mcp._tool_manager.get_tool("get_order_status").fn
    result = await tool_fn(order_id=ORDER_ID, ctx=_make_ctx(cached_client))

    # Renamed field — no longer "download_urls"
    assert "download_urls" not in result, "download_urls was renamed to api_download_endpoints"
    assert "api_download_endpoints" in result
    assert result["api_download_endpoints"].get("image") is not None


@pytest.mark.asyncio
async def test_list_orders_includes_skyfi_order_url() -> None:
    """list_orders includes skyfi_order_url inside each order dict for web browser viewing.

    skyfi_order_url (https://app.skyfi.com/orders/{id}) is the correct browser link.
    download_image_url is an authenticated API endpoint and must NOT be given to users
    as a clickable link — doing so produces 'Missing api key' in the browser.
    """
    order = _make_tasking_order()
    cached_client = MagicMock()
    cached_client.list_orders = AsyncMock(
        return_value=ListOrdersResponse(total=1, orders=[order])
    )

    tool_fn = mcp._tool_manager.get_tool("list_orders").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    order_data = result["orders"][0]
    assert "skyfi_order_url" in order_data, "skyfi_order_url must be inside each order dict"
    assert "app.skyfi.com/orders/" in order_data["skyfi_order_url"]
    assert str(ORDER_ID) in order_data["skyfi_order_url"]


@pytest.mark.asyncio
async def test_get_order_status_includes_skyfi_order_url() -> None:
    """get_order_status includes skyfi_order_url at top level and inside order dict."""
    order = _make_tasking_order("CREATED")
    cached_client = MagicMock()
    cached_client.get_order = AsyncMock(return_value=order)

    tool_fn = mcp._tool_manager.get_tool("get_order_status").fn
    result = await tool_fn(order_id=ORDER_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert "skyfi_order_url" in result
    assert "app.skyfi.com/orders/" in result["skyfi_order_url"]
    assert ORDER_ID in result["skyfi_order_url"]
    # Also present inside order dict for consistency
    assert "skyfi_order_url" in result["order"]
    # summary references the web URL
    assert "app.skyfi.com/orders/" in result["summary"]


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
