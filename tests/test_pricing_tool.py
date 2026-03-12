"""Tests for the get_pricing MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.server import mcp

SIMPLE_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"

PRICING_RESPONSE = {
    "HIGH_DAY": {"pricePerSqKm": 3.0},
    "VERY_HIGH_DAY": {"pricePerSqKm": 8.0},
    "SAR_HIGH": {"pricePerSqKm": 6.0},
}


def _make_ctx(cached_client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    mock_settings = MagicMock()
    mock_settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": mock_settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_get_pricing_no_aoi() -> None:
    """get_pricing without AOI returns full pricing matrix."""
    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(return_value=PRICING_RESPONSE)

    tool_fn = mcp._tool_manager.get_tool("get_pricing").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert "pricing_matrix" in result
    assert result["aoi_area_sq_km"] is None
    assert "summary" in result


@pytest.mark.asyncio
async def test_get_pricing_with_wkt_aoi() -> None:
    """get_pricing with AOI calculates area estimate."""
    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(return_value=PRICING_RESPONSE)

    tool_fn = mcp._tool_manager.get_tool("get_pricing").fn
    result = await tool_fn(aoi=SIMPLE_WKT, ctx=_make_ctx(cached_client))

    assert result["aoi_area_sq_km"] is not None
    assert result["aoi_area_sq_km"] > 0


@pytest.mark.asyncio
async def test_get_pricing_api_error_returns_error() -> None:
    """SkyFi API failure returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(side_effect=Exception("SkyFi down"))

    tool_fn = mcp._tool_manager.get_tool("get_pricing").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


@pytest.mark.asyncio
async def test_get_pricing_summary_not_empty() -> None:
    """Summary is non-empty even with empty pricing data."""
    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(return_value={})

    tool_fn = mcp._tool_manager.get_tool("get_pricing").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
async def test_get_pricing_filters_applied_in_result() -> None:
    """Filter parameters appear in the result."""
    cached_client = MagicMock()
    cached_client.get_pricing = AsyncMock(return_value=PRICING_RESPONSE)

    tool_fn = mcp._tool_manager.get_tool("get_pricing").fn
    result = await tool_fn(product_type="DAY", resolution="HIGH", ctx=_make_ctx(cached_client))

    assert result["filters_applied"]["product_type"] == "DAY"
    assert result["filters_applied"]["resolution"] == "HIGH"
