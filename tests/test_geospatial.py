"""Tests for geospatial tools: helper functions and resolve_location."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest

from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools.geospatial import (
    MAX_AREA_SQ_KM,
    MAX_VERTICES,
    _bounding_box_to_polygon,
    _calculate_aoi_area_sync,
    _calculate_area_sq_km,
    _clip_to_max_area,
    _create_aoi_from_point_sync,
    resolve_location,
)

# ---------------------------------------------------------------------------
# _bounding_box_to_polygon
# ---------------------------------------------------------------------------


def test_bounding_box_to_polygon_shape() -> None:
    """Bounding box converts to a valid rectangular polygon."""
    polygon = _bounding_box_to_polygon(["30.0", "34.0", "-100.0", "-96.0"])
    assert polygon.is_valid
    bounds = polygon.bounds  # (minx, miny, maxx, maxy)
    assert abs(bounds[0] - (-100.0)) < 0.001
    assert abs(bounds[2] - (-96.0)) < 0.001


# ---------------------------------------------------------------------------
# _calculate_area_sq_km
# ---------------------------------------------------------------------------


def test_calculate_area_sq_km_small_box() -> None:
    """A ~1 degree box near the equator has reasonable area."""
    polygon = _bounding_box_to_polygon(["0.0", "1.0", "0.0", "1.0"])
    area = _calculate_area_sq_km(polygon)
    # ~1 degree box at equator ≈ 12,000 sq km
    assert 10_000 < area < 15_000


def test_calculate_area_sq_km_never_negative() -> None:
    """Area calculation always returns a non-negative value."""
    polygon = _bounding_box_to_polygon(["10.0", "11.0", "20.0", "21.0"])
    area = _calculate_area_sq_km(polygon)
    assert area >= 0


# ---------------------------------------------------------------------------
# _create_aoi_from_point_sync
# ---------------------------------------------------------------------------


def test_create_aoi_from_point_returns_wkt() -> None:
    """create_aoi_from_point_sync returns valid WKT."""
    from shapely import wkt as shapely_wkt

    wkt, _actual_area = _create_aoi_from_point_sync(30.0, -97.7, 100.0)
    polygon = shapely_wkt.loads(wkt)
    assert polygon.is_valid
    assert wkt.startswith("POLYGON")


def test_create_aoi_from_point_area_close() -> None:
    """Actual area is within 5% of requested area."""
    _, actual_area = _create_aoi_from_point_sync(30.0, -97.7, 100.0)
    assert abs(actual_area - 100.0) / 100.0 < 0.05


def test_create_aoi_from_point_high_latitude() -> None:
    """Works at high latitude (near poles)."""
    wkt, _actual_area = _create_aoi_from_point_sync(70.0, 25.0, 50.0)
    assert wkt.startswith("POLYGON")
    assert _actual_area > 0


def test_create_aoi_from_point_large_area() -> None:
    """Large area request returns polygon with close to requested area."""
    _, actual_area = _create_aoi_from_point_sync(0.0, 0.0, 10_000.0)
    assert abs(actual_area - 10_000.0) / 10_000.0 < 0.05


# ---------------------------------------------------------------------------
# _calculate_aoi_area_sync
# ---------------------------------------------------------------------------

SMALL_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"


def test_calculate_aoi_area_valid_polygon() -> None:
    """Valid small polygon returns positive area and vertex count."""
    result = _calculate_aoi_area_sync(SMALL_WKT)
    assert result["area_sq_km"] > 0
    assert result["vertex_count"] == 4  # 5 coords, first==last → 4 vertices
    assert result["is_valid"] is True
    assert result["validation_message"] is None


def test_calculate_aoi_area_invalid_wkt() -> None:
    """Invalid WKT string is handled gracefully."""
    result = _calculate_aoi_area_sync("NOT VALID WKT")
    assert result["is_valid"] is False
    assert result["area_sq_km"] == 0.0
    assert "Invalid WKT" in (result["validation_message"] or "")


def test_calculate_aoi_area_too_many_vertices() -> None:
    """Polygon with > 500 vertices is flagged as invalid."""
    # Create a polygon with 501+ vertices (circle approximation)

    n = 502
    coords = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i in range(n)]
    coords.append(coords[0])  # close
    coords_str = ", ".join(f"{x:.6f} {y:.6f}" for x, y in coords)
    wkt = f"POLYGON(({coords_str}))"
    result = _calculate_aoi_area_sync(wkt)
    assert result["vertex_count"] > MAX_VERTICES
    assert result["is_valid"] is False
    assert result["validation_message"] is not None


def test_calculate_aoi_area_known_area() -> None:
    """Known polygon has area within 1% of expected."""
    # This is ~4 km x 4 km box near Austin, TX
    # Rough expected area from bounding box ~ 20 sq km
    result = _calculate_aoi_area_sync(SMALL_WKT)
    # ~0.04° x 0.04° box at 30°N is roughly 16-20 sq km
    assert 10 < result["area_sq_km"] < 30


# ---------------------------------------------------------------------------
# _clip_to_max_area
# ---------------------------------------------------------------------------


def test_clip_to_max_area_reduces_polygon() -> None:
    """Clipping a large polygon produces one close to MAX_AREA_SQ_KM."""
    # Russia bounding box: S=41, N=82, W=19, E=191 (wraps around 180)
    # Use a simpler oversized box
    big_polygon = _bounding_box_to_polygon(["0.0", "60.0", "0.0", "60.0"])
    centroid = big_polygon.centroid
    clipped = _clip_to_max_area(big_polygon, centroid)
    clipped_area = _calculate_area_sq_km(clipped)
    # Should be approximately MAX_AREA_SQ_KM
    assert abs(clipped_area - MAX_AREA_SQ_KM) / MAX_AREA_SQ_KM < 0.05


# ---------------------------------------------------------------------------
# resolve_location — WKT passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_location_wkt_passthrough() -> None:
    """WKT polygons are returned unchanged."""
    wkt = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"
    result_wkt, _note = await resolve_location(wkt)
    assert result_wkt == wkt
    assert _note is None


@pytest.mark.asyncio
async def test_resolve_location_wkt_with_whitespace() -> None:
    """WKT with leading whitespace is handled."""
    wkt = "  POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))  "
    result_wkt, _note = await resolve_location(wkt)
    assert result_wkt == wkt.strip()


# ---------------------------------------------------------------------------
# resolve_location — geocoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_location_geocodes_place_name() -> None:
    """Place name triggers Nominatim and returns WKT."""
    mock_raw = {
        "lat": 33.749,
        "lon": -84.388,
        "display_name": "Atlanta, Georgia, USA",
        "boundingbox": ["33.6", "33.9", "-84.6", "-84.2"],
    }

    with patch("purveyor.tools.geospatial._geocode_sync", return_value=mock_raw):
        wkt, note = await resolve_location("Atlanta, GA")
    assert "POLYGON" in wkt
    assert note is None  # Atlanta bbox is small, no clipping


@pytest.mark.asyncio
async def test_resolve_location_clips_large_bbox() -> None:
    """Oversized bounding box is clipped and location_note is returned."""
    # A 40°x40° box is way over 500k sq km
    mock_raw = {
        "lat": 60.0,
        "lon": 90.0,
        "display_name": "Russia",
        "boundingbox": ["41.0", "81.0", "20.0", "180.0"],
    }

    with patch("purveyor.tools.geospatial._geocode_sync", return_value=mock_raw):
        wkt, note = await resolve_location("Russia")
    assert "POLYGON" in wkt
    assert note is not None
    assert "clipped" in note.lower() or "exceeding" in note.lower()


@pytest.mark.asyncio
async def test_resolve_location_cache_hit() -> None:
    """Cached geocode result is returned without Nominatim call."""
    import json

    wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    cached_data = json.dumps({"wkt": wkt, "location_note": None}).encode()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=cached_data)
    mock_cache.set = AsyncMock()

    with patch("purveyor.tools.geospatial._geocode_sync") as mock_geocode:
        result_wkt, _note = await resolve_location("Austin, TX", cache=mock_cache)
    mock_geocode.assert_not_called()
    assert result_wkt == wkt


@pytest.mark.asyncio
async def test_resolve_location_geocode_failure_raises_tool_error() -> None:
    """Failed geocode raises ToolError with NOMINATIM_UNAVAILABLE."""
    with patch("purveyor.tools.geospatial._geocode_sync", return_value=None):
        with pytest.raises(ToolError) as exc_info:
            await resolve_location("Nonexistent Place XYZ123")
    assert exc_info.value.code == ErrorCode.NOMINATIM_UNAVAILABLE


@pytest.mark.asyncio
async def test_resolve_location_no_boundingbox_creates_point_aoi() -> None:
    """When Nominatim returns no bounding box, a point-based AOI is created."""
    mock_raw = {
        "lat": 37.774,
        "lon": -122.419,
        "display_name": "San Francisco",
        "boundingbox": None,
    }

    with patch("purveyor.tools.geospatial._geocode_sync", return_value=mock_raw):
        wkt, note = await resolve_location("San Francisco")
    assert "POLYGON" in wkt
    assert note is None
