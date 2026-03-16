"""Tests for get_preview_url MCP tool and build_skyfi_preview_url helper."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.server import mcp
from purveyor.tools.preview import build_skyfi_preview_url

ARCHIVE_ID = (
    "SENTINEL1_CREODIAS:S1A_IW_GRDH_1SDV_20260308T003503_20260308T003528_063529_07FBA3_040F_COG"
)
SIMPLE_WKT = (
    "POLYGON((-97.738 30.271, -97.738 30.263, -97.748 30.263, -97.748 30.271, -97.738 30.271))"
)


# ---------------------------------------------------------------------------
# build_skyfi_preview_url (pure function)
# ---------------------------------------------------------------------------


def test_build_skyfi_preview_url_basic() -> None:
    url = build_skyfi_preview_url(
        archive_id=ARCHIVE_ID,
        aoi_wkt=SIMPLE_WKT,
    )
    assert url.startswith(f"https://app.skyfi.com/explore/open/crop/{ARCHIVE_ID}")
    assert "aoi=POLYGON" in url
    assert "%28" in url  # encoded opening parenthesis
    assert " " not in url  # no raw spaces


def test_build_skyfi_preview_url_encodes_spaces() -> None:
    wkt = "POLYGON((-97.7 30.2, -97.7 30.3, -97.8 30.3, -97.8 30.2, -97.7 30.2))"
    url = build_skyfi_preview_url("some-id", wkt)
    assert " " not in url


def test_build_skyfi_preview_url_encodes_parens() -> None:
    url = build_skyfi_preview_url("test-id", SIMPLE_WKT)
    # Parentheses should be percent-encoded
    assert "(" not in url
    assert ")" not in url
    assert "%28" in url
    assert "%29" in url


def test_build_skyfi_preview_url_archive_id_in_path() -> None:
    archive_id = str(uuid.uuid4())
    url = build_skyfi_preview_url(archive_id, SIMPLE_WKT)
    assert f"/explore/open/crop/{archive_id}" in url


# ---------------------------------------------------------------------------
# get_preview_url MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preview_url_tool_returns_url() -> None:
    """get_preview_url tool returns a correctly formed URL."""
    tool_fn = mcp._tool_manager.get_tool("get_preview_url").fn
    result = await tool_fn(archive_id=ARCHIVE_ID, aoi_wkt=SIMPLE_WKT)

    assert isinstance(result, str)
    assert result.startswith(f"https://app.skyfi.com/explore/open/crop/{ARCHIVE_ID}")
    assert "aoi=POLYGON" in result
    assert " " not in result


# ---------------------------------------------------------------------------
# search_archives includes preview_url
# ---------------------------------------------------------------------------


def _make_search_ctx(cached_client: MagicMock) -> MagicMock:
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
async def test_search_archives_includes_preview_url() -> None:
    """Each archive in search_archives results includes a preview_url."""
    from purveyor.core.skyfi_types import ApiProvider, ArchiveResponse, GetArchivesResponse

    archive_id = str(uuid.uuid4())
    archive = ArchiveResponse(
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
        overlap_ratio=0.85,
        overlap_sqkm=42.5,
    )
    response = GetArchivesResponse(archives=[archive], total=1, next_page=None)

    cached_client = MagicMock()
    cached_client.search_archives = AsyncMock(return_value=response)

    tool_fn = mcp._tool_manager.get_tool("search_archives").fn
    result = await tool_fn(location=SIMPLE_WKT, ctx=_make_search_ctx(cached_client))

    assert isinstance(result, dict)
    assert len(result["archives"]) == 1
    archive_result = result["archives"][0]

    assert "preview_url" in archive_result
    preview_url = archive_result["preview_url"]
    assert f"/explore/open/crop/{archive_id}" in preview_url
    assert "aoi=POLYGON" in preview_url
    assert " " not in preview_url
