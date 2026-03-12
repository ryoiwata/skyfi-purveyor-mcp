"""Hypothesis property-based tests for geospatial functions."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from purveyor.tools.geospatial import (
    _bounding_box_to_polygon,
    _calculate_aoi_area_sync,
    _calculate_area_sq_km,
    _create_aoi_from_point_sync,
)


@given(
    lat=st.floats(min_value=-85, max_value=85),
    lon=st.floats(min_value=-170, max_value=170),
    area=st.floats(min_value=0.01, max_value=500),
)
@settings(max_examples=50, deadline=5000)
def test_create_aoi_produces_valid_polygon(lat: float, lon: float, area: float) -> None:
    """Any valid lat/lon/area produces a valid WKT polygon with area close to requested."""
    from shapely import wkt as shapely_wkt

    wkt, actual_area = _create_aoi_from_point_sync(lat, lon, area)
    polygon = shapely_wkt.loads(wkt)
    assert polygon.is_valid, f"Invalid polygon for lat={lat}, lon={lon}, area={area}"
    assert actual_area > 0
    assert abs(actual_area - area) / area < 0.1  # within 10%


@given(
    area=st.floats(min_value=0.1, max_value=1000),
)
@settings(max_examples=30, deadline=5000)
def test_create_aoi_area_positive(area: float) -> None:
    """Actual area returned is always positive."""
    _, actual_area = _create_aoi_from_point_sync(30.0, -97.0, area)
    assert actual_area > 0


@given(
    lat=st.floats(min_value=-89, max_value=89),
    lon=st.floats(min_value=-179, max_value=179),
    area=st.floats(min_value=1.0, max_value=100.0),
)
@settings(max_examples=30, deadline=5000)
def test_create_aoi_polygon_is_closed(lat: float, lon: float, area: float) -> None:
    """Created AOI polygon is always a closed ring (first == last coordinate)."""
    from shapely import wkt as shapely_wkt

    wkt, _ = _create_aoi_from_point_sync(lat, lon, area)
    polygon = shapely_wkt.loads(wkt)
    coords = list(polygon.exterior.coords)
    assert coords[0] == coords[-1], "Polygon exterior ring is not closed"


@given(
    lat=st.floats(min_value=-85, max_value=85),
    lon=st.floats(min_value=-170, max_value=170),
    area=st.floats(min_value=1.0, max_value=100.0),
)
@settings(max_examples=30, deadline=5000)
def test_create_aoi_centroid_near_center(lat: float, lon: float, area: float) -> None:
    """The centroid of the created polygon is within 1° of the requested center."""
    from shapely import wkt as shapely_wkt

    wkt, _ = _create_aoi_from_point_sync(lat, lon, area)
    polygon = shapely_wkt.loads(wkt)
    centroid = polygon.centroid
    assert abs(centroid.y - lat) < 1.0
    assert abs(centroid.x - lon) < 1.0


@given(
    south=st.floats(min_value=-89, max_value=0),
    north=st.floats(min_value=0, max_value=89),
    west=st.floats(min_value=-179, max_value=0),
    east=st.floats(min_value=0, max_value=179),
)
@settings(max_examples=30, deadline=5000)
def test_calculate_area_never_negative(
    south: float, north: float, west: float, east: float
) -> None:
    """Area calculation never returns negative."""
    assume(north > south + 0.01 and east > west + 0.01)
    polygon = _bounding_box_to_polygon(
        [str(south), str(north), str(west), str(east)]
    )
    area = _calculate_area_sq_km(polygon)
    assert area >= 0


@given(
    wkt=st.just("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"),
)
def test_calculate_aoi_area_sync_stable(wkt: str) -> None:
    """_calculate_aoi_area_sync returns consistent results for same input."""
    result1 = _calculate_aoi_area_sync(wkt)
    result2 = _calculate_aoi_area_sync(wkt)
    assert result1["area_sq_km"] == result2["area_sq_km"]
    assert result1["vertex_count"] == result2["vertex_count"]
