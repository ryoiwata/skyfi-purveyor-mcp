"""Tests for OSM tools: helper functions and HTTP-level integration tests."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools.osm import (
    MAX_VERTICES,
    _build_way_polygon,
    _calculate_area_sq_km,
    _geojson_to_wkt,
    _haversine_km,
    _nominatim_search,
    _nominatim_search_boundary,
    _overpass_query,
)

# ---------------------------------------------------------------------------
# _geojson_to_wkt — sync helper tests
# ---------------------------------------------------------------------------

SIMPLE_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-97.76, 30.24],
            [-97.72, 30.24],
            [-97.72, 30.28],
            [-97.76, 30.28],
            [-97.76, 30.24],
        ]
    ],
}

MULTIPOLYGON_GEOJSON = {
    "type": "MultiPolygon",
    "coordinates": [
        # Small polygon
        [[[-97.76, 30.24], [-97.75, 30.24], [-97.75, 30.25], [-97.76, 30.24]]],
        # Larger polygon
        [
            [
                [-97.76, 30.24],
                [-97.72, 30.24],
                [-97.72, 30.28],
                [-97.76, 30.28],
                [-97.76, 30.24],
            ]
        ],
    ],
}


def test_geojson_to_wkt_simple_polygon() -> None:
    """Simple polygon GeoJSON converts to valid WKT."""
    from shapely import wkt as shapely_wkt

    wkt, note = _geojson_to_wkt(SIMPLE_POLYGON_GEOJSON)
    assert wkt.startswith("POLYGON")
    assert note is None
    geom = shapely_wkt.loads(wkt)
    assert geom.is_valid


def test_geojson_to_wkt_multipolygon_takes_largest() -> None:
    """MultiPolygon: the largest polygon by area is selected."""
    from shapely import wkt as shapely_wkt

    wkt, _note = _geojson_to_wkt(MULTIPOLYGON_GEOJSON)
    geom = shapely_wkt.loads(wkt)
    assert geom.geom_type == "Polygon"
    assert geom.is_valid
    # The larger polygon spans 0.04° x 0.04°; the small one spans 0.01° x 0.01°
    bounds = geom.bounds
    assert abs(bounds[2] - bounds[0]) > 0.02  # width > 0.02°


def test_geojson_to_wkt_simplification() -> None:
    """Polygon with >500 vertices is simplified and returns a note."""
    from shapely import wkt as shapely_wkt

    # Build a circle approximation with 600 points
    n = 600
    coords = [
        (-97.0 + 0.01 * math.cos(2 * math.pi * i / n), 30.0 + 0.01 * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    coords.append(coords[0])  # close ring
    geojson = {"type": "Polygon", "coordinates": [coords]}

    wkt, note = _geojson_to_wkt(geojson)
    geom = shapely_wkt.loads(wkt)

    assert note is not None
    assert "Simplified" in note
    assert len(list(geom.exterior.coords)) <= MAX_VERTICES
    assert geom.is_valid


def test_geojson_to_wkt_produces_valid_wkt() -> None:
    """All GeoJSON conversions produce WKT parseable by Shapely."""
    from shapely import wkt as shapely_wkt

    for geojson in [SIMPLE_POLYGON_GEOJSON, MULTIPOLYGON_GEOJSON]:
        wkt, _ = _geojson_to_wkt(geojson)
        geom = shapely_wkt.loads(wkt)
        assert geom.is_valid


# ---------------------------------------------------------------------------
# _build_way_polygon — sync helper tests
# ---------------------------------------------------------------------------


def test_build_way_polygon_valid() -> None:
    """Valid coordinate list produces a WKT polygon with positive area."""
    from shapely import wkt as shapely_wkt

    coords = [
        (-97.76, 30.24),
        (-97.72, 30.24),
        (-97.72, 30.28),
        (-97.76, 30.28),
    ]
    result = _build_way_polygon(coords)
    assert "wkt" in result
    assert "area_km2" in result
    assert "center_lat" in result
    assert "center_lon" in result
    assert result["area_km2"] > 0

    geom = shapely_wkt.loads(result["wkt"])
    assert geom.is_valid


def test_build_way_polygon_simplification() -> None:
    """Way polygon with >500 vertices gets simplified, note returned."""
    from shapely import wkt as shapely_wkt

    n = 600
    coords = [
        (math.cos(2 * math.pi * i / n) * 0.01, math.sin(2 * math.pi * i / n) * 0.01)
        for i in range(n)
    ]
    result = _build_way_polygon(coords)

    assert result.get("note") is not None
    geom = shapely_wkt.loads(result["wkt"])
    assert len(list(geom.exterior.coords)) <= MAX_VERTICES


# ---------------------------------------------------------------------------
# _haversine_km — distance helper tests
# ---------------------------------------------------------------------------


def test_haversine_km_zero_distance() -> None:
    """Same point → distance is 0."""
    assert _haversine_km(30.0, -97.7, 30.0, -97.7) == pytest.approx(0.0, abs=0.001)


def test_haversine_km_known_distance() -> None:
    """Austin TX to NYC is roughly 2,400-2,500 km."""
    # Austin: 30.26, -97.74  NYC: 40.71, -74.01
    dist = _haversine_km(30.26, -97.74, 40.71, -74.01)
    assert 2400 < dist < 2600


def test_haversine_km_always_non_negative() -> None:
    """Distance is always non-negative."""
    pairs = [
        (0, 0, 0, 0),
        (90, 0, -90, 0),
        (0, -180, 0, 180),
        (45, 90, -45, -90),
    ]
    for lat1, lon1, lat2, lon2 in pairs:
        assert _haversine_km(lat1, lon1, lat2, lon2) >= 0


# ---------------------------------------------------------------------------
# _calculate_area_sq_km — area helper tests
# ---------------------------------------------------------------------------


def test_calculate_area_sq_km_positive() -> None:
    """Area of a valid polygon is positive."""
    from shapely.geometry import box

    geom = box(-97.76, 30.24, -97.72, 30.28)
    area = _calculate_area_sq_km(geom)
    assert area > 0


def test_calculate_area_sq_km_never_negative() -> None:
    """Area is never negative for any valid polygon."""
    from shapely.geometry import box

    geom = box(0.0, 0.0, 1.0, 1.0)
    assert _calculate_area_sq_km(geom) >= 0


# ---------------------------------------------------------------------------
# _nominatim_search — HTTP mock tests
# ---------------------------------------------------------------------------

NOMINATIM_SEARCH_RESPONSE = [
    {
        "place_id": 12345,
        "osm_type": "relation",
        "osm_id": 1453306,
        "category": "boundary",
        "type": "national_park",
        "display_name": "Yellowstone National Park, Park County, Wyoming, US",
        "name": "Yellowstone National Park",
        "boundingbox": ["44.13", "45.11", "-111.15", "-109.83"],
        "geojson": SIMPLE_POLYGON_GEOJSON,
    }
]


@pytest.mark.asyncio
async def test_nominatim_search_returns_results() -> None:
    """_nominatim_search returns parsed JSON list on 200."""
    with patch("purveyor.tools.osm.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=NOMINATIM_SEARCH_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        results = await _nominatim_search("Yellowstone", "https://nominatim.openstreetmap.org")

    assert len(results) == 1
    assert results[0]["name"] == "Yellowstone National Park"


@pytest.mark.asyncio
async def test_nominatim_search_http_error_raises_tool_error() -> None:
    """_nominatim_search raises ToolError on HTTP failure."""
    with patch("purveyor.tools.osm.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ToolError) as exc_info:
            await _nominatim_search("Yellowstone", "https://nominatim.openstreetmap.org")

    assert exc_info.value.code == ErrorCode.NOMINATIM_UNAVAILABLE


# ---------------------------------------------------------------------------
# _nominatim_search_boundary — HTTP mock tests
# ---------------------------------------------------------------------------

NOMINATIM_BOUNDARY_RESPONSE = [
    {
        "place_id": 99999,
        "osm_type": "relation",
        "osm_id": 111111,
        "category": "boundary",
        "type": "administrative",
        "display_name": "Austin, Travis County, Texas, United States",
        "name": "Austin",
        "boundingbox": ["30.13", "30.52", "-97.94", "-97.56"],
        "extratags": {"admin_level": "8"},
        "geojson": SIMPLE_POLYGON_GEOJSON,
    }
]


@pytest.mark.asyncio
async def test_nominatim_search_boundary_returns_results() -> None:
    """_nominatim_search_boundary returns admin boundary data."""
    with patch("purveyor.tools.osm.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=NOMINATIM_BOUNDARY_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        results = await _nominatim_search_boundary(
            "Austin, Texas", "https://nominatim.openstreetmap.org"
        )

    assert len(results) == 1
    assert results[0]["name"] == "Austin"
    assert results[0]["extratags"]["admin_level"] == "8"


# ---------------------------------------------------------------------------
# _overpass_query — HTTP mock tests
# ---------------------------------------------------------------------------

OVERPASS_RESPONSE = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 33.9425,
            "lon": -118.4081,
        },
        {
            "type": "way",
            "id": 123456,
            "nodes": [1],
            "tags": {"name": "Los Angeles International Airport", "aeroway": "aerodrome"},
            "center": {"lat": 33.9425, "lon": -118.4081},
        },
    ]
}


@pytest.mark.asyncio
async def test_overpass_query_returns_elements() -> None:
    """_overpass_query returns the elements list from Overpass JSON."""
    with patch("purveyor.tools.osm.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=OVERPASS_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        elements = await _overpass_query("[out:json]; (way[aeroway=aerodrome];); out body;")

    assert len(elements) == 2
    way = next(el for el in elements if el["type"] == "way")
    assert way["tags"]["name"] == "Los Angeles International Airport"


@pytest.mark.asyncio
async def test_overpass_query_http_error_raises_tool_error() -> None:
    """_overpass_query raises ToolError on HTTP failure."""
    with patch("purveyor.tools.osm.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ToolError) as exc_info:
            await _overpass_query("any query")

    assert exc_info.value.code == ErrorCode.NOMINATIM_UNAVAILABLE


# ---------------------------------------------------------------------------
# WKT validity guarantee
# ---------------------------------------------------------------------------


def test_all_geojson_conversions_produce_valid_wkt() -> None:
    """All test GeoJSON fixtures produce valid Shapely-parseable WKT."""
    from shapely import wkt as shapely_wkt

    fixtures = [SIMPLE_POLYGON_GEOJSON, MULTIPOLYGON_GEOJSON]
    for geojson in fixtures:
        wkt, _ = _geojson_to_wkt(geojson)
        geom = shapely_wkt.loads(wkt)
        assert geom.is_valid, f"Invalid WKT from {geojson['type']}: {wkt[:100]}"


def test_simplified_polygon_respects_vertex_limit() -> None:
    """Simplified polygon always has ≤500 vertices."""
    from shapely import wkt as shapely_wkt

    for n in [501, 600, 1000, 2000]:
        coords = [
            (math.cos(2 * math.pi * i / n) * 0.05, math.sin(2 * math.pi * i / n) * 0.05)
            for i in range(n)
        ]
        coords.append(coords[0])
        geojson = {"type": "Polygon", "coordinates": [coords]}

        wkt, note = _geojson_to_wkt(geojson)
        geom = shapely_wkt.loads(wkt)
        vertex_count = len(list(geom.exterior.coords)) - 1  # -1 because first == last

        assert vertex_count <= MAX_VERTICES, f"n={n}: {vertex_count} vertices > {MAX_VERTICES}"
        assert note is not None, f"n={n}: expected simplification note"


# ---------------------------------------------------------------------------
# Live API tests (skipped in CI)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_nominatim_search_yellowstone() -> None:
    """Live: search Nominatim for Yellowstone, get a polygon back."""
    results = await _nominatim_search(
        "Yellowstone National Park", "https://nominatim.openstreetmap.org"
    )
    assert len(results) > 0
    assert any("Yellowstone" in r.get("display_name", "") for r in results)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_nominatim_boundary_austin() -> None:
    """Live: get boundary for Austin, TX."""
    results = await _nominatim_search_boundary(
        "Austin, Texas", "https://nominatim.openstreetmap.org"
    )
    assert len(results) > 0
    assert any("Austin" in r.get("display_name", "") for r in results)
