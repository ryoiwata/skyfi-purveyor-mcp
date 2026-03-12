"""Geospatial MCP tools: geocode_location, create_aoi_from_point, calculate_aoi_area.

Design decisions applied:
- §6: Oversized AOI clipping (> 500k sq km → clip to centroid)
- §12: Nominatim rate limit — global asyncio.Semaphore(1)
- §12: GEOCODING_BASE_URL for custom Nominatim endpoint
- §14: Tool summaries are agent-facing briefings, not user prose
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError

# Type alias to satisfy mypy strict [type-arg] on the 3-param generic Context
McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)

# SkyFi limits
MAX_VERTICES = 500
MAX_AREA_SQ_KM = 500_000.0

# Global Nominatim rate-limit semaphore (1 req/sec per Design Decision §12)
_nominatim_semaphore = asyncio.Semaphore(1)


# ---------------------------------------------------------------------------
# Internal helpers (sync — run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _geocode_sync(place_name: str, base_url: str) -> dict[str, Any] | None:
    """Synchronous Nominatim geocode call. Run via asyncio.to_thread."""
    from urllib.parse import urlparse

    from geopy.geocoders import Nominatim

    parsed = urlparse(base_url)
    domain = parsed.netloc or "nominatim.openstreetmap.org"
    scheme = parsed.scheme or "https"

    geolocator = Nominatim(
        user_agent="Purveyor-MCP/1.0",
        domain=domain,
        scheme=scheme,
    )
    try:
        location = geolocator.geocode(
            place_name,
            exactly_one=True,
            addressdetails=False,
            namedetails=False,
        )
    except Exception as exc:
        log.warning("nominatim_error", error=str(exc))
        return None

    if location is None:
        return None

    raw = location.raw
    return {
        "lat": location.latitude,
        "lon": location.longitude,
        "display_name": location.address,
        "boundingbox": raw.get("boundingbox"),  # [south, north, west, east] strings
    }


def _calculate_area_sq_km(polygon: Any) -> float:  # polygon: shapely.geometry.Polygon
    """Calculate polygon area in sq km using equal-area projection."""
    from pyproj import Transformer
    from shapely.ops import transform

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    projected = transform(transformer.transform, polygon)
    return float(projected.area) / 1_000_000.0


def _bounding_box_to_polygon(boundingbox: list[str]) -> Any:  # shapely.geometry.Polygon
    """Convert Nominatim boundingbox [S, N, W, E] to a Shapely polygon."""
    from shapely.geometry import box as shapely_box

    south, north, west, east = (float(x) for x in boundingbox)
    return shapely_box(west, south, east, north)


def _clip_to_max_area(polygon: Any, centroid: Any) -> Any:  # shapely types
    """Clip a polygon to MAX_AREA_SQ_KM centered on the centroid.

    Returns a square box in WGS84 coordinates.
    """

    from pyproj import Transformer
    from shapely.geometry import box as shapely_box
    from shapely.ops import transform

    lat = centroid.y
    lon = centroid.x

    local_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)

    side_m = math.sqrt(MAX_AREA_SQ_KM * 1_000_000.0)
    half = side_m / 2.0

    local_box = shapely_box(-half, -half, half, half)
    return transform(to_wgs84.transform, local_box)


def _create_aoi_from_point_sync(lat: float, lon: float, area_sq_km: float) -> tuple[str, float]:
    """Create a square AOI polygon centered on a point. Returns (wkt, actual_area_sq_km)."""

    from pyproj import Transformer
    from shapely.geometry import box as shapely_box
    from shapely.ops import transform

    local_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)

    side_m = math.sqrt(area_sq_km * 1_000_000.0)
    half = side_m / 2.0

    local_box = shapely_box(-half, -half, half, half)
    wgs84_box = transform(to_wgs84.transform, local_box)

    actual_area = _calculate_area_sq_km(wgs84_box)
    return str(wgs84_box.wkt), actual_area


def _calculate_aoi_area_sync(aoi_wkt: str) -> dict[str, Any]:
    """Parse WKT and calculate area + validate limits."""
    from shapely import wkt as shapely_wkt
    from shapely.errors import WKTReadingError

    try:
        polygon = shapely_wkt.loads(aoi_wkt)
    except (WKTReadingError, Exception) as exc:
        return {
            "area_sq_km": 0.0,
            "vertex_count": 0,
            "is_valid": False,
            "validation_message": f"Invalid WKT: {exc}",
        }

    vertex_count = len(polygon.exterior.coords) - 1  # -1 because first == last
    area_sq_km = _calculate_area_sq_km(polygon)
    is_valid = bool(polygon.is_valid)
    messages: list[str] = []

    if not is_valid:
        messages.append("Polygon is not geometrically valid (self-intersecting or degenerate).")
    if vertex_count > MAX_VERTICES:
        messages.append(
            f"Polygon has {vertex_count} vertices, exceeding the SkyFi limit of {MAX_VERTICES}."
        )
    if area_sq_km > MAX_AREA_SQ_KM:
        messages.append(
            f"Area {area_sq_km:.0f} sq km exceeds the SkyFi search limit "
            f"of {MAX_AREA_SQ_KM:,.0f} sq km."
        )

    return {
        "area_sq_km": round(area_sq_km, 2),
        "vertex_count": vertex_count,
        "is_valid": is_valid and vertex_count <= MAX_VERTICES and area_sq_km <= MAX_AREA_SQ_KM,
        "validation_message": " ".join(messages) or None,
    }


# ---------------------------------------------------------------------------
# resolve_location helper (Design Decision §6)
# ---------------------------------------------------------------------------


async def resolve_location(
    location: str,
    geocoding_base_url: str = "https://nominatim.openstreetmap.org",
    cache: Any = None,
) -> tuple[str, str | None]:
    """Resolve a location string to a WKT polygon.

    If location looks like WKT (starts with POLYGON), return it unchanged.
    Otherwise geocode via Nominatim, clip oversized results to 500k sq km.

    Args:
        location: Place name OR WKT POLYGON string.
        geocoding_base_url: Nominatim-compatible base URL.
        cache: Optional CacheBackend for geocode result caching.

    Returns:
        (wkt_polygon, location_note) where location_note is None unless
        the AOI was clipped.

    Raises:
        ToolError: If geocoding fails or produces no result.
    """
    import json

    # WKT passthrough
    if location.strip().upper().startswith("POLYGON"):
        return location.strip(), None

    # Check geocode cache
    normalized = location.strip().lower()
    cache_key = f"geocode:{normalized}"

    if cache is not None:
        cached = await cache.get(cache_key)
        if cached is not None:
            cached_data = json.loads(cached)
            return cached_data["wkt"], cached_data.get("location_note")

    # Rate-limited Nominatim call
    async with _nominatim_semaphore:
        raw = await asyncio.to_thread(_geocode_sync, location, geocoding_base_url)

    if raw is None:
        raise ToolError(
            code=ErrorCode.NOMINATIM_UNAVAILABLE,
            message=(
                f"Could not geocode location: '{location}'. "
                "Try a more specific place name or provide a WKT polygon."
            ),
        )

    lat: float = raw["lat"]
    lon: float = raw["lon"]
    display_name: str = raw["display_name"]
    boundingbox: list[str] | None = raw.get("boundingbox")

    if boundingbox:
        polygon = await asyncio.to_thread(_bounding_box_to_polygon, boundingbox)
        area_sq_km = await asyncio.to_thread(_calculate_area_sq_km, polygon)
    else:
        # No bounding box — create small square around point
        wkt_no_bbox, _ = await asyncio.to_thread(
            _create_aoi_from_point_sync, lat, lon, 25.0  # 5x5 km default
        )
        # Cache and return
        if cache is not None:
            data = {"wkt": wkt_no_bbox, "location_note": None}
            await cache.set(cache_key, json.dumps(data).encode(), 3600)
        return wkt_no_bbox, None

    location_note: str | None = None
    if area_sq_km > MAX_AREA_SQ_KM:
        original_area = area_sq_km
        centroid = polygon.centroid
        clipped = await asyncio.to_thread(_clip_to_max_area, polygon, centroid)
        polygon = clipped
        area_sq_km = await asyncio.to_thread(_calculate_area_sq_km, clipped)
        location_note = (
            f"Location '{display_name}' has a bounding box of {original_area:,.0f} sq km, "
            f"exceeding the SkyFi search limit of {MAX_AREA_SQ_KM:,.0f} sq km. "
            f"Clipped to {area_sq_km:,.0f} sq km centered on the geographic center."
        )
        log.info(
            "aoi_clipped",
            location=location,
            original_area_sq_km=round(original_area),
            clipped_area_sq_km=round(area_sq_km),
        )

    wkt_result = str(polygon.wkt)

    # Cache result
    if cache is not None:
        data = {"wkt": wkt_result, "location_note": location_note}
        await cache.set(cache_key, json.dumps(data).encode(), 3600)

    return wkt_result, location_note


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register geospatial tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def geocode_location(
        place_name: str,
        ctx: McpContext,
    ) -> Any:
        """Geocode a place name to coordinates and a suggested AOI polygon.

        Args:
            place_name: Human-readable location (e.g. "Port of Los Angeles", "Manaus, Brazil").
        """
        log.info("tool_geocode_location", place_name=place_name)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        settings = lc["settings"]
        cache = lc["cache"]

        try:
            async with _nominatim_semaphore:
                raw = await asyncio.to_thread(
                    _geocode_sync, place_name, settings.geocoding_base_url
                )
        except Exception as exc:
            return ToolError(
                code=ErrorCode.NOMINATIM_UNAVAILABLE,
                message=f"Geocoding service error: {exc}",
            ).to_call_tool_result()

        if raw is None:
            return ToolError(
                code=ErrorCode.NOMINATIM_UNAVAILABLE,
                message=f"No results found for '{place_name}'. Try a more specific location.",
            ).to_call_tool_result()

        lat: float = raw["lat"]
        lon: float = raw["lon"]
        display_name: str = raw["display_name"]
        boundingbox: list[str] | None = raw.get("boundingbox")

        aoi_wkt: str | None = None
        bounding_box_result: list[float] | None = None

        if boundingbox:
            polygon = await asyncio.to_thread(_bounding_box_to_polygon, boundingbox)
            aoi_wkt = str(polygon.wkt)
            south, north, west, east = (float(x) for x in boundingbox)
            bounding_box_result = [south, north, west, east]
        else:
            wkt, _ = await asyncio.to_thread(_create_aoi_from_point_sync, lat, lon, 25.0)
            aoi_wkt = wkt

        result = {
            "coordinates": [lat, lon],
            "bounding_box": bounding_box_result,
            "display_name": display_name,
            "aoi_wkt": aoi_wkt,
            "summary": (
                f"Geocoded '{place_name}' → {display_name}. "
                f"Coordinates: {lat:.4f}°, {lon:.4f}°. AOI polygon ready for use."
            ),
        }

        # Cache for 1 hour
        import json as _json

        cache_key = f"geocode:{place_name.strip().lower()}"
        payload = _json.dumps({"wkt": aoi_wkt, "location_note": None}).encode()
        await cache.set(cache_key, payload, 3600)

        return result

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def create_aoi_from_point(
        latitude: float,
        longitude: float,
        area_sq_km: float,
        ctx: McpContext,
    ) -> Any:
        """Create a square AOI polygon centered on a lat/lon point.

        Uses accurate azimuthal equidistant projection for the area calculation.

        Args:
            latitude: Latitude in decimal degrees (-90 to 90).
            longitude: Longitude in decimal degrees (-180 to 180).
            area_sq_km: Desired area in square kilometers.
        """
        log.info("tool_create_aoi_from_point", lat=latitude, lon=longitude, area=area_sq_km)

        if not (-90 <= latitude <= 90):
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Latitude {latitude} is out of range (-90 to 90).",
            ).to_call_tool_result()
        if not (-180 <= longitude <= 180):
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Longitude {longitude} is out of range (-180 to 180).",
            ).to_call_tool_result()
        if area_sq_km <= 0:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Area must be positive, got {area_sq_km}.",
            ).to_call_tool_result()

        wkt, actual_area = await asyncio.to_thread(
            _create_aoi_from_point_sync, latitude, longitude, area_sq_km
        )

        return {
            "aoi_wkt": wkt,
            "actual_area_sq_km": round(actual_area, 3),
            "requested_area_sq_km": area_sq_km,
            "summary": (
                f"Created {actual_area:.1f} sq km square AOI centered on "
                f"{latitude:.4f}°, {longitude:.4f}°."
            ),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def calculate_aoi_area(
        aoi_wkt: str,
        ctx: McpContext,
    ) -> Any:
        """Calculate the area of a WKT polygon and validate against SkyFi limits.

        Validates: max 500 vertices, max 500,000 sq km for searches.

        Args:
            aoi_wkt: WKT POLYGON string.
        """
        log.info("tool_calculate_aoi_area")

        result = await asyncio.to_thread(_calculate_aoi_area_sync, aoi_wkt)

        summary_parts = [
            f"Area: {result['area_sq_km']:,.1f} sq km. Vertices: {result['vertex_count']}."
        ]
        if result["is_valid"]:
            summary_parts.append("Valid for SkyFi searches.")
        else:
            summary_parts.append(f"Invalid: {result['validation_message']}")

        result["summary"] = " ".join(summary_parts)
        return result
