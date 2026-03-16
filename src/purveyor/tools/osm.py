"""OpenStreetMap MCP tools: search_osm, get_osm_boundary, get_osm_features_in_area.

Uses Nominatim (search/boundary) and Overpass API (features-in-area).
No API key required. Respects Nominatim 1 req/sec rate limit via shared semaphore.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx
import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from shapely import wkt as shapely_wkt

from purveyor.core.errors import ErrorCode, ToolError

# Share Nominatim semaphore with geospatial.py for global 1 req/sec rate limit
from purveyor.tools.geospatial import _nominatim_semaphore
from purveyor.tools.preview import build_skyfi_explore_url_from_bbox

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)

OSM_USER_AGENT = "Purveyor-MCP/1.0 (https://github.com/ryoiwata/skyfi-purveyor-mcp)"
OVERPASS_BASE = "https://overpass-api.de/api/interpreter"
MAX_VERTICES = 500

# Minimum useful area for a search AOI in sq km — filters degenerate convex hulls
# from point-like or near-collinear geometries (e.g. a 3-point LineString)
_MIN_AREA_SQ_KM = 0.01


# ---------------------------------------------------------------------------
# Sync helpers — run via asyncio.to_thread for CPU-bound Shapely work
# ---------------------------------------------------------------------------


def _geojson_to_wkt(
    geojson_geometry: dict[str, Any], max_vertices: int = MAX_VERTICES
) -> tuple[str, str | None]:
    """Convert a GeoJSON geometry dict to WKT, simplifying if vertex count exceeds limit.

    For MultiPolygon, takes the largest polygon by area.
    For non-polygon types, returns the convex hull.

    Returns:
        (wkt_string, simplification_note) — note is None if no simplification occurred.
    """
    from shapely.geometry import shape

    geom = shape(geojson_geometry)

    # MultiPolygon → take the largest polygon
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)

    # Non-polygon types (LineString, Point, etc.) → convex hull
    if not hasattr(geom, "exterior"):
        geom = geom.convex_hull

    # convex_hull of a degenerate/collinear geometry (e.g. 3 collinear points) can
    # return a LineString or Point instead of a Polygon.  Those have no usable area,
    # so raise immediately — the caller's try/except will skip this result and the
    # area filter (_MIN_AREA_SQ_KM) provides a second guard in search_osm.
    if not hasattr(geom, "exterior"):
        raise ValueError(
            f"Geometry reduced to non-polygon ({geom.geom_type}) after convex_hull — "
            "likely collinear or degenerate input."
        )

    note: str | None = None
    coords = list(geom.exterior.coords)
    if len(coords) > max_vertices:
        original_count = len(coords)
        tolerance = 0.001
        while len(list(geom.exterior.coords)) > max_vertices and tolerance < 1.0:
            geom = geom.simplify(tolerance, preserve_topology=True)
            tolerance *= 2
        final_count = len(list(geom.exterior.coords))
        note = (
            f"Simplified from {original_count} to {final_count} vertices "
            f"to meet SkyFi's {MAX_VERTICES} vertex limit."
        )

    return str(geom.wkt), note


def _calculate_area_sq_km(geom: Any) -> float:
    """Calculate the area of a Shapely geometry in sq km using equal-area projection."""
    from pyproj import Transformer
    from shapely.ops import transform

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    projected = transform(transformer.transform, geom)
    return float(projected.area) / 1_000_000.0


def _build_way_polygon(coords: list[tuple[float, float]]) -> dict[str, Any]:
    """Build a Shapely Polygon from (lon, lat) coordinate pairs and compute metrics.

    Returns a dict with: wkt, area_km2, center_lat, center_lon, and optional note.
    """
    from shapely.geometry import Polygon

    geom = Polygon(coords)
    if not geom.is_valid:
        geom = geom.buffer(0)  # attempt to fix self-intersections

    exterior_coords = list(geom.exterior.coords)
    note: str | None = None
    if len(exterior_coords) > MAX_VERTICES:
        original_count = len(exterior_coords)
        tolerance = 0.001
        while len(list(geom.exterior.coords)) > MAX_VERTICES and tolerance < 1.0:
            geom = geom.simplify(tolerance, preserve_topology=True)
            tolerance *= 2
        final_count = len(list(geom.exterior.coords))
        note = (
            f"Simplified from {original_count} to {final_count} vertices "
            f"to meet SkyFi's {MAX_VERTICES} vertex limit."
        )

    area_km2 = _calculate_area_sq_km(geom)
    centroid = geom.centroid

    result: dict[str, Any] = {
        "wkt": str(geom.wkt),
        "area_km2": round(area_km2, 2),
        "center_lat": centroid.y,
        "center_lon": centroid.x,
    }
    if note:
        result["note"] = note
    return result


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in km between two lat/lon points."""
    r = 6371.0
    lat1_r, lon1_r, lat2_r, lon2_r = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# HTTP helpers — testable module-level async functions
# ---------------------------------------------------------------------------


async def _nominatim_search(
    query: str,
    nominatim_base: str,
    *,
    feature_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Fetch Nominatim search results with polygon geometry.

    Rate-limited to 1 req/sec via the shared _nominatim_semaphore.
    Returns the raw JSON list from Nominatim.

    Raises:
        ToolError: On HTTP failure.
    """
    params: dict[str, Any] = {
        "q": query,
        "format": "jsonv2",
        "polygon_geojson": 1,
        "limit": min(max(1, limit), 10),
        "addressdetails": 0,
    }
    if feature_type:
        params["featureType"] = feature_type

    headers = {"User-Agent": OSM_USER_AGENT}

    try:
        async with _nominatim_semaphore:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{nominatim_base.rstrip('/')}/search",
                    params=params,
                    headers=headers,
                )
        response.raise_for_status()
        return list(response.json())
    except httpx.HTTPError as exc:
        raise ToolError(
            code=ErrorCode.NOMINATIM_UNAVAILABLE,
            message=f"Nominatim search failed: {exc}",
        ) from exc


async def _nominatim_search_boundary(
    place_name: str,
    nominatim_base: str,
) -> list[dict[str, Any]]:
    """Fetch Nominatim results with address details and extratags for boundary selection.

    Rate-limited to 1 req/sec via the shared _nominatim_semaphore.

    Raises:
        ToolError: On HTTP failure.
    """
    params: dict[str, Any] = {
        "q": place_name,
        "format": "jsonv2",
        "polygon_geojson": 1,
        "limit": 10,
        "addressdetails": 1,
        "extratags": 1,
    }
    headers = {"User-Agent": OSM_USER_AGENT}

    try:
        async with _nominatim_semaphore:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{nominatim_base.rstrip('/')}/search",
                    params=params,
                    headers=headers,
                )
        response.raise_for_status()
        return list(response.json())
    except httpx.HTTPError as exc:
        raise ToolError(
            code=ErrorCode.NOMINATIM_UNAVAILABLE,
            message=f"Nominatim search failed: {exc}",
        ) from exc


async def _overpass_query(query: str) -> list[dict[str, Any]]:
    """Execute an Overpass QL query and return the elements list.

    Raises:
        ToolError: On HTTP failure.
    """
    headers = {"User-Agent": OSM_USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(
                OVERPASS_BASE,
                data={"data": query},
                headers=headers,
            )
        response.raise_for_status()
        return list(response.json().get("elements", []))
    except httpx.HTTPError as exc:
        raise ToolError(
            code=ErrorCode.NOMINATIM_UNAVAILABLE,
            message=f"Overpass API request failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register OpenStreetMap tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def search_osm(
        query: str,
        feature_type: str | None = None,
        limit: int = 5,
        *,
        ctx: McpContext,
    ) -> Any:
        """Search OpenStreetMap for places, boundaries, and features.

        Returns actual geographic boundaries (not just center points) that can be
        used directly as AOIs for satellite imagery searches and orders.

        Args:
            query: Search term (e.g. "Yellowstone National Park", "Port of Rotterdam",
                "JFK Airport").
            feature_type: Optional OSM feature filter. Examples: "boundary", "aeroway",
                "landuse", "natural", "waterway".
            limit: Maximum number of results to return (default 5, max 10).
        """
        log.info("tool_search_osm", query=query, feature_type=feature_type, limit=limit)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        settings = lc["settings"]

        try:
            data = await _nominatim_search(
                query,
                settings.geocoding_base_url,
                feature_type=feature_type,
                limit=limit,
            )
        except ToolError as exc:
            return exc.to_call_tool_result()

        results: list[dict[str, Any]] = []
        for item in data:
            geojson = item.get("geojson")
            if not geojson:
                continue

            try:
                wkt, note = await asyncio.to_thread(_geojson_to_wkt, geojson)
                geom = shapely_wkt.loads(wkt)
                area_km2 = await asyncio.to_thread(_calculate_area_sq_km, geom)
            except Exception as exc:
                log.warning("osm_geojson_parse_error", query=query, error=str(exc))
                continue

            # Skip degenerate results (e.g. near-collinear LineString whose convex
            # hull collapses to a point or sliver) — useless as a satellite AOI
            if area_km2 < _MIN_AREA_SQ_KM:
                log.debug(
                    "osm_result_skipped_tiny_area",
                    query=query,
                    display_name=item.get("display_name"),
                    area_km2=area_km2,
                )
                continue

            # Nominatim boundingbox order: [south, north, west, east]
            bbox_raw = item.get("boundingbox", [])
            bbox = (
                [
                    float(bbox_raw[2]),
                    float(bbox_raw[0]),
                    float(bbox_raw[3]),
                    float(bbox_raw[1]),
                ]
                if len(bbox_raw) == 4
                else []
            )

            skyfi_explore_url: str | None = None
            if bbox:
                try:
                    skyfi_explore_url = build_skyfi_explore_url_from_bbox(bbox)
                except Exception as exc:
                    log.warning("osm_explore_url_build_error", error=str(exc))

            entry: dict[str, Any] = {
                "name": item.get("name")
                or (item.get("display_name") or "").split(",")[0].strip(),
                "osm_type": item.get("osm_type"),
                "osm_id": item.get("osm_id"),
                "category": item.get("category"),
                "type": item.get("type"),
                "display_name": item.get("display_name"),
                "bbox": bbox,
                "aoi_wkt": wkt,
                "area_km2": round(area_km2, 2),
            }
            if skyfi_explore_url:
                entry["skyfi_explore_url"] = skyfi_explore_url
            if note:
                entry["note"] = note
            results.append(entry)

        if not results:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message=f"No OSM results with boundaries found for '{query}'.",
            ).to_call_tool_result()

        areas = [r["area_km2"] for r in results]
        area_summary = (
            f"{areas[0]:,.0f} km²"
            if len(areas) == 1
            else f"{min(areas):,.0f}-{max(areas):,.0f} km²"
        )

        return {
            "results": results,
            "count": len(results),
            "summary": (
                f"Found {len(results)} OSM result(s) for '{query}'. "
                f"Area: {area_summary}. "
                f"Top result: {results[0]['display_name']}. "
                f"WKT polygons ready for use as AOIs."
            ),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_osm_boundary(
        place_name: str,
        admin_level: int | None = None,
        *,
        ctx: McpContext,
    ) -> Any:
        """Get the administrative boundary polygon of a city, state, or country.

        Returns the official boundary as a WKT polygon suitable for use as an AOI.

        Args:
            place_name: Name of the place (e.g. "Austin, Texas", "France", "Tokyo").
            admin_level: Optional OSM admin level (2=country, 4=state/province, 6=county,
                8=city/town). If not specified, returns the most specific match.
        """
        log.info("tool_get_osm_boundary", place_name=place_name, admin_level=admin_level)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        settings = lc["settings"]

        try:
            data = await _nominatim_search_boundary(place_name, settings.geocoding_base_url)
        except ToolError as exc:
            return exc.to_call_tool_result()

        if not data:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message=f"No boundary found for '{place_name}'.",
            ).to_call_tool_result()

        # Filter by admin_level if specified
        candidates: list[dict[str, Any]] = data
        if admin_level is not None:
            filtered = [
                item
                for item in data
                if (item.get("extratags") or {}).get("admin_level") == str(admin_level)
            ]
            if filtered:
                candidates = filtered

        # Prefer boundary/administrative types
        best: dict[str, Any] = candidates[0]
        for item in candidates:
            if item.get("category") == "boundary" or item.get("type") == "administrative":
                best = item
                break

        geojson = best.get("geojson")
        if not geojson:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message=f"No boundary polygon found for '{place_name}'.",
            ).to_call_tool_result()

        try:
            wkt, simplification_note = await asyncio.to_thread(_geojson_to_wkt, geojson)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Failed to parse boundary geometry: {exc}",
            ).to_call_tool_result()

        from shapely import wkt as shapely_wkt

        geom = shapely_wkt.loads(wkt)
        area_km2 = await asyncio.to_thread(_calculate_area_sq_km, geom)

        # Parse admin_level from extratags
        extratags = best.get("extratags") or {}
        result_admin_level: int | None = None
        raw_level = extratags.get("admin_level")
        if raw_level is not None:
            try:
                result_admin_level = int(raw_level)
            except (ValueError, TypeError):
                pass

        # Nominatim boundingbox: [south, north, west, east]
        bbox_raw = best.get("boundingbox", [])
        bbox = (
            [
                float(bbox_raw[2]),
                float(bbox_raw[0]),
                float(bbox_raw[3]),
                float(bbox_raw[1]),
            ]
            if len(bbox_raw) == 4
            else []
        )

        warning: str | None = None
        if area_km2 > 500_000:
            warning = (
                f"Area ({area_km2:,.0f} km²) exceeds SkyFi's 500,000 km² search limit. "
                f"Consider using a sub-region."
            )
        elif area_km2 > 10_000:
            warning = (
                f"Area ({area_km2:,.0f} km²) may exceed SkyFi's typical order size limits "
                f"(5-10,000 km2). Suitable for archive searches, not tasking orders."
            )

        skyfi_explore_url: str | None = None
        if bbox:
            try:
                skyfi_explore_url = build_skyfi_explore_url_from_bbox(bbox)
            except Exception as exc:
                log.warning("osm_explore_url_build_error", place_name=place_name, error=str(exc))

        result: dict[str, Any] = {
            "name": best.get("name") or place_name,
            "admin_level": result_admin_level,
            "display_name": best.get("display_name"),
            "aoi_wkt": wkt,
            "area_km2": round(area_km2, 2),
            "bbox": bbox,
            "warning": warning,
        }
        if skyfi_explore_url:
            result["skyfi_explore_url"] = skyfi_explore_url
        if simplification_note:
            result["simplification_note"] = simplification_note

        summary = f"Boundary for '{place_name}': {area_km2:,.0f} km²."
        if warning:
            summary += f" {warning}"
        else:
            summary += " Within SkyFi search limits."
        result["summary"] = summary

        return result

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_osm_features_in_area(
        feature_type: str,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
        limit: int = 10,
        *,
        ctx: McpContext,
    ) -> Any:
        """Find specific geographic features near a location using the Overpass API.

        Search for airports, ports, military bases, power plants, stadiums, etc.
        within a radius of a center point. Returns their locations and boundaries.

        Args:
            feature_type: Type of feature to search for. Common values:
                "aeroway=aerodrome" (airports), "landuse=port" (ports),
                "landuse=military" (military), "leisure=stadium" (stadiums),
                "amenity=university" (universities), "natural=water" (lakes).
            latitude: Center point latitude.
            longitude: Center point longitude.
            radius_km: Search radius in kilometers (default 10).
            limit: Maximum results to return (default 10).
        """
        log.info(
            "tool_get_osm_features_in_area",
            feature_type=feature_type,
            lat=latitude,
            lon=longitude,
            radius_km=radius_km,
        )

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
        if radius_km <= 0:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"radius_km must be positive, got {radius_km}.",
            ).to_call_tool_result()

        # Parse "key=value" or bare "key"
        if "=" in feature_type:
            key, _, value = feature_type.partition("=")
            osm_filter = f'["{key.strip()}"="{value.strip()}"]'
        else:
            osm_filter = f'["{feature_type.strip()}"]'

        radius_m = int(radius_km * 1000)
        around = f"around:{radius_m},{latitude},{longitude}"

        # Include center output so relations have a center point even without full geometry
        overpass_query = (
            f"[out:json][timeout:25];\n"
            f"(\n"
            f"  way{osm_filter}({around});\n"
            f"  relation{osm_filter}({around});\n"
            f");\n"
            f"out body center;\n"
            f">;\n"
            f"out skel qt;"
        )

        try:
            elements = await _overpass_query(overpass_query)
        except ToolError as exc:
            return exc.to_call_tool_result()

        # Build node coordinate lookup from skeleton output
        nodes: dict[int, tuple[float, float]] = {}  # id → (lon, lat)
        feature_elements: list[dict[str, Any]] = []

        for el in elements:
            el_type = el.get("type")
            if el_type == "node" and "lat" in el and "lon" in el:
                nodes[el["id"]] = (el["lon"], el["lat"])
            elif el_type in ("way", "relation") and el.get("tags"):
                feature_elements.append(el)

        results: list[dict[str, Any]] = []
        for el in feature_elements[: max(1, limit)]:
            tags = el.get("tags", {})
            name = (
                tags.get("name")
                or tags.get("name:en")
                or f"{feature_type} (unnamed)"
            )
            el_type = el.get("type")
            osm_id = el.get("id")

            # Overpass provides a center field with body+center output
            center_data = el.get("center") or {}
            center_lat: float = float(center_data.get("lat", latitude))
            center_lon: float = float(center_data.get("lon", longitude))

            wkt: str | None = None
            area_km2 = 0.0
            simplification_note: str | None = None

            if el_type == "way":
                way_node_ids: list[int] = el.get("nodes", [])
                coords = [nodes[n] for n in way_node_ids if n in nodes]
                if len(coords) >= 3:
                    try:
                        geom_data = await asyncio.to_thread(_build_way_polygon, coords)
                        wkt = geom_data["wkt"]
                        area_km2 = float(geom_data["area_km2"])
                        center_lat = float(geom_data["center_lat"])
                        center_lon = float(geom_data["center_lon"])
                        simplification_note = geom_data.get("note")
                    except Exception as exc:
                        log.warning("osm_way_polygon_error", osm_id=osm_id, error=str(exc))
            # Relations: use the Overpass-provided center point (full geometry too complex)

            dist_km = _haversine_km(latitude, longitude, center_lat, center_lon)

            entry: dict[str, Any] = {
                "name": name,
                "osm_id": osm_id,
                "feature_type": feature_type,
                "center": {"lat": round(center_lat, 6), "lon": round(center_lon, 6)},
                "distance_km": round(dist_km, 2),
            }
            if wkt:
                entry["aoi_wkt"] = wkt
                entry["area_km2"] = round(area_km2, 2)
            if simplification_note:
                entry["note"] = simplification_note

            results.append(entry)

        if not results:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message=(
                    f"No '{feature_type}' features found within {radius_km} km "
                    f"of ({latitude}, {longitude})."
                ),
            ).to_call_tool_result()

        nearest = results[0]
        return {
            "features": results,
            "count": len(results),
            "search_center": {"lat": latitude, "lon": longitude},
            "search_radius_km": radius_km,
            "summary": (
                f"Found {len(results)} '{feature_type}' feature(s) within {radius_km} km. "
                f"Nearest: {nearest['name']} ({nearest['distance_km']} km away)."
            ),
        }
