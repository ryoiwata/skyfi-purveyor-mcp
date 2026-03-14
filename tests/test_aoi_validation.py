"""Tests for AOI size validation in create_archive_order and create_tasking_order."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.core.skyfi_types import ApiProvider, Archive
from purveyor.server import mcp
from purveyor.tools.orders import SKYFI_MAX_AOI_KM2, SKYFI_MIN_AOI_KM2

# Polygons chosen for predictable area sizes:
# Tiny (~1 km²): 0.01° x 0.01° near equator — well below 5 km² minimum
TINY_WKT = "POLYGON((0 0, 0.01 0, 0.01 0.01, 0 0.01, 0 0))"

# Valid (~17 km²): 0.04° x 0.04° in Texas — fits 5-10,000 km² window
VALID_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"

# Huge (~1.2 million km²): 10° x 10° box — well above 10,000 km² maximum
HUGE_WKT = "POLYGON((-5 -5, 5 -5, 5 5, -5 5, -5 -5))"

ARCHIVE_ID = str(uuid.uuid4())


def _make_archive() -> Archive:
    return Archive(
        archive_id=ARCHIVE_ID,
        provider=ApiProvider.PLANET,
        constellation="dove",
        product_type="DAY",
        platform_resolution=3.0,
        resolution="VERY HIGH",
        capture_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
        cloud_coverage_percent=5.0,
        off_nadir_angle=10.0,
        footprint=VALID_WKT,
        min_sq_km=1.0,
        max_sq_km=100.0,
        price_for_one_square_km=5.0,
        price_for_one_square_km_cents=500,
        price_full_scene=500.0,
        open_data=False,
        total_area_square_km=50.0,
        delivery_time_hours=12.0,
        gsd=3.0,
    )


def _make_archive_order_ctx(cached_client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    settings = MagicMock()
    settings.confirmation_base_url = "http://localhost:8000"
    settings.server_port = 8000
    settings.fernet_key = b"A" * 32
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": MagicMock(),
    }
    return ctx


def _make_tasking_order_ctx() -> MagicMock:
    ctx = MagicMock()
    settings = MagicMock()
    settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    settings.confirmation_base_url = "http://localhost:8000"
    settings.server_port = 8000
    settings.fernet_key = b"A" * 32
    ctx.request_context.lifespan_context = {
        "cached_client": MagicMock(),
        "settings": settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": MagicMock(),
    }
    return ctx


def _parse_error(result: object) -> dict[str, object]:
    from mcp.types import CallToolResult

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    return json.loads(result.content[0].text)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_constants_are_correct() -> None:
    assert SKYFI_MIN_AOI_KM2 == 5.0
    assert SKYFI_MAX_AOI_KM2 == 10_000.0


# ---------------------------------------------------------------------------
# create_archive_order — AOI validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_archive_order_rejects_oversized_aoi() -> None:
    """AOI > 10,000 km² returns aoi_too_large error before creating a token."""
    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=_make_archive())

    tool_fn = mcp._tool_manager.get_tool("create_archive_order").fn
    result = await tool_fn(
        aoi=HUGE_WKT,
        archive_id=ARCHIVE_ID,
        ctx=_make_archive_order_ctx(cached_client),
    )

    error = _parse_error(result)
    assert error["code"] == "aoi_too_large"
    assert "10,000" in error["message"]
    assert "create_aoi_from_point" in error["message"]


@pytest.mark.asyncio
async def test_create_archive_order_rejects_undersized_aoi() -> None:
    """AOI < 5 km² returns invalid_input error before creating a token."""
    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=_make_archive())

    tool_fn = mcp._tool_manager.get_tool("create_archive_order").fn
    result = await tool_fn(
        aoi=TINY_WKT,
        archive_id=ARCHIVE_ID,
        ctx=_make_archive_order_ctx(cached_client),
    )

    error = _parse_error(result)
    assert error["code"] == "invalid_input"
    assert "5" in error["message"]
    assert "create_aoi_from_point" in error["message"]


@pytest.mark.asyncio
async def test_create_archive_order_accepts_valid_aoi() -> None:
    """AOI within 5-10,000 km² passes validation — not rejected with an AOI size error."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=_make_archive())

    tool_fn = mcp._tool_manager.get_tool("create_archive_order").fn
    result = await tool_fn(
        aoi=VALID_WKT,
        archive_id=ARCHIVE_ID,
        ctx=_make_archive_order_ctx(cached_client),
    )

    # If an error is returned, it must NOT be an AOI size error.
    # (Token/DB failures are expected without real infrastructure.)
    if isinstance(result, CallToolResult) and result.isError:
        err = json.loads(result.content[0].text)
        assert err.get("code") not in ("aoi_too_large",), (
            f"Valid AOI incorrectly rejected: {err}"
        )
        assert "AOI too small" not in err.get("message", ""), (
            f"Valid AOI incorrectly rejected as too small: {err}"
        )


# ---------------------------------------------------------------------------
# create_tasking_order — AOI validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tasking_order_rejects_oversized_aoi() -> None:
    """Tasking order with AOI > 10,000 km² returns aoi_too_large error."""
    tool_fn = mcp._tool_manager.get_tool("create_tasking_order").fn
    result = await tool_fn(
        location=HUGE_WKT,
        product_type="DAY",
        resolution="VERY HIGH",
        window_start="2024-07-01T00:00:00",
        window_end="2024-07-31T00:00:00",
        ctx=_make_tasking_order_ctx(),
    )

    error = _parse_error(result)
    assert error["code"] == "aoi_too_large"
    assert "10,000" in error["message"]
    assert "create_aoi_from_point" in error["message"]


@pytest.mark.asyncio
async def test_create_tasking_order_rejects_undersized_aoi() -> None:
    """Tasking order with AOI < 5 km² returns invalid_input error."""
    tool_fn = mcp._tool_manager.get_tool("create_tasking_order").fn
    result = await tool_fn(
        location=TINY_WKT,
        product_type="DAY",
        resolution="VERY HIGH",
        window_start="2024-07-01T00:00:00",
        window_end="2024-07-31T00:00:00",
        ctx=_make_tasking_order_ctx(),
    )

    error = _parse_error(result)
    assert error["code"] == "invalid_input"
    assert "5" in error["message"]
    assert "create_aoi_from_point" in error["message"]


# ---------------------------------------------------------------------------
# search_archives — includes aoi_area_km2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_archives_includes_aoi_area() -> None:
    """search_archives result includes aoi_area_km2 field."""
    from purveyor.core.skyfi_types import ApiProvider, ArchiveResponse, GetArchivesResponse

    archive = ArchiveResponse(
        archive_id=str(uuid.uuid4()),
        provider=ApiProvider.PLANET,
        constellation="dove",
        product_type="DAY",
        platform_resolution=3.0,
        resolution="VERY HIGH",
        capture_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
        cloud_coverage_percent=5.0,
        off_nadir_angle=10.0,
        footprint=VALID_WKT,
        min_sq_km=1.0,
        max_sq_km=100.0,
        price_for_one_square_km=5.0,
        price_for_one_square_km_cents=500,
        price_full_scene=500.0,
        open_data=False,
        total_area_square_km=50.0,
        delivery_time_hours=12.0,
        gsd=3.0,
        overlap_ratio=0.85,
        overlap_sqkm=42.5,
    )
    response = GetArchivesResponse(archives=[archive], total=1, next_page=None)

    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(return_value=response)

    ctx = MagicMock()
    mock_settings = MagicMock()
    mock_settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": mock_settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": None,
    }

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=VALID_WKT, ctx=ctx)

    assert isinstance(result, dict)
    assert "aoi_area_km2" in result
    assert result["aoi_area_km2"] is not None
    assert result["aoi_area_km2"] > 0
