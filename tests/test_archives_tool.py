"""Tests for search_archives and get_archive_details MCP tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from purveyor.core.skyfi_types import (
    ApiProvider,
    Archive,
    ArchiveResponse,
    GetArchivesResponse,
)
from purveyor.server import mcp

ARCHIVE_ID = str(uuid.uuid4())
SIMPLE_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"


def _make_archive(archive_id: str = ARCHIVE_ID) -> Archive:
    return Archive(
        archive_id=archive_id,
        provider=ApiProvider.PLANET,
        constellation="dove",
        product_type="DAY",
        platform_resolution=3.0,
        resolution="VERY HIGH",
        capture_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
        cloud_coverage_percent=5.0,
        off_nadir_angle=10.0,
        footprint=SIMPLE_WKT,
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


def _make_archive_response(archive_id: str = ARCHIVE_ID) -> ArchiveResponse:
    return ArchiveResponse(
        **_make_archive(archive_id).model_dump(),
        overlap_ratio=0.85,
        overlap_sqkm=42.5,
    )


def _make_archives_response(count: int = 1) -> GetArchivesResponse:
    archives = [_make_archive_response(str(uuid.uuid4())) for _ in range(count)]
    return GetArchivesResponse(archives=archives, total=count, next_page=None)


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


# ---------------------------------------------------------------------------
# search_archives
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_archives_with_wkt_returns_results() -> None:
    """WKT location returns archives without geocoding."""
    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(return_value=_make_archives_response(3))

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=SIMPLE_WKT, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["total"] == 3
    assert len(result["archives"]) == 3
    assert "Found 3 archives" in result["summary"]
    # Each archive must have a skyfi_url
    for archive in result["archives"]:
        assert "skyfi_url" in archive
        assert archive["skyfi_url"].startswith("https://app.skyfi.com/explore/archive/")
        assert archive["archive_id"] in archive["skyfi_url"]


@pytest.mark.asyncio
async def test_get_archive_details_includes_skyfi_url() -> None:
    """get_archive_details includes skyfi_url in response and summary."""
    archive = _make_archive()
    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=archive)

    tool_fn = mcp._tool_manager.get_tool("get_archive_details").fn
    result = await tool_fn(archive_id=ARCHIVE_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    expected_url = f"https://app.skyfi.com/explore/archive/{ARCHIVE_ID}"
    assert result["skyfi_url"] == expected_url
    assert expected_url in result["summary"]


@pytest.mark.asyncio
async def test_search_archives_with_place_name_geocodes() -> None:
    """Place name is geocoded before search."""
    mock_raw = {
        "lat": 30.27,
        "lon": -97.74,
        "display_name": "Austin, TX",
        "boundingbox": ["30.1", "30.5", "-97.9", "-97.6"],
    }

    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(return_value=_make_archives_response(2))

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    with patch("purveyor.tools.geospatial._geocode_sync", return_value=mock_raw):
        result = await tool_fn(location="Austin, TX", ctx=_make_ctx(cached_client))

    assert result["total"] == 2
    cached_client.search_archives.assert_called_once()


@pytest.mark.asyncio
async def test_search_archives_no_results_returns_error() -> None:
    """Empty results returns isError=True with no_results code."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(
        return_value=GetArchivesResponse(archives=[], total=0, next_page=None)
    )

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=SIMPLE_WKT, ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    import json
    content = json.loads(result.content[0].text)
    assert content["code"] == "no_results"


@pytest.mark.asyncio
async def test_search_archives_summary_contains_dates() -> None:
    """Summary includes date range when archives have timestamps."""
    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(return_value=_make_archives_response(1))

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=SIMPLE_WKT, ctx=_make_ctx(cached_client))

    assert "2024-06-15" in result["summary"]


@pytest.mark.asyncio
async def test_search_archives_invalid_date_returns_error() -> None:
    """Invalid date format returns invalid_input error."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        from_date="not-a-date",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    import json
    assert json.loads(result.content[0].text)["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_search_archives_open_data_filter() -> None:
    """open_data=True is passed to the search request."""
    captured_request = {}

    async def capture_search(req: object) -> GetArchivesResponse:
        captured_request["req"] = req
        return _make_archives_response(1)

    cached_client = MagicMock()
    cached_client.search_archives = capture_search

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    await tool_fn(location=SIMPLE_WKT, open_data=True, ctx=_make_ctx(cached_client))

    req = captured_request["req"]
    assert req.open_data is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_search_archives_api_error_returns_error() -> None:
    """SkyFi API failure returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(side_effect=Exception("connection refused"))

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=SIMPLE_WKT, ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# get_archive_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_archive_details_returns_archive() -> None:
    """get_archive_details returns archive data and summary."""
    archive = _make_archive()
    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(return_value=archive)

    tool_fn = mcp._tool_manager.get_tool("get_archive_details").fn
    result = await tool_fn(archive_id=ARCHIVE_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["archive"]["archive_id"] == ARCHIVE_ID
    assert "PLANET" in result["summary"]


@pytest.mark.asyncio
async def test_get_archive_details_api_error() -> None:
    """Failed fetch returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_archive = AsyncMock(side_effect=Exception("not found"))

    tool_fn = mcp._tool_manager.get_tool("get_archive_details").fn
    result = await tool_fn(archive_id="nonexistent-id", ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
