"""Preview URL builder for SkyFi archive images."""

from __future__ import annotations

from urllib.parse import quote, quote_plus

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def build_skyfi_preview_url(archive_id: str, aoi_wkt: str) -> str:
    """Build a SkyFi explore/crop URL for previewing an archive image in the browser."""
    encoded_aoi = quote(aoi_wkt, safe="")
    return f"https://app.skyfi.com/explore/open/crop/{archive_id}?aoi={encoded_aoi}"


def build_skyfi_explore_url(aoi_wkt: str) -> str:
    """Build a SkyFi tasking URL filtered to an AOI."""
    encoded_aoi = quote_plus(aoi_wkt)
    return f"https://app.skyfi.com/tasking?s=DAY&r=HIGH&aoi={encoded_aoi}"


def build_skyfi_explore_url_from_wkt(aoi_wkt: str, max_url_vertices: int = 25) -> str:
    """Build a SkyFi tasking URL from a WKT polygon, simplified for URL use.

    Simplifies the polygon to at most `max_url_vertices` vertices and rounds
    coordinates to 6 decimal places, keeping the URL short while preserving
    the actual polygon shape (not a bounding box rectangle).

    Falls back to the raw WKT if Shapely is unavailable.
    """
    try:
        from shapely import wkt as shapely_wkt

        geom = shapely_wkt.loads(aoi_wkt)
        if not hasattr(geom, "exterior"):
            # MultiPolygon or GeometryCollection — take largest polygon
            if geom.geom_type == "MultiPolygon":
                geom = max(geom.geoms, key=lambda g: g.area)
            else:
                geom = geom.convex_hull

        tolerance = 0.01
        while len(list(geom.exterior.coords)) > max_url_vertices and tolerance < 10.0:
            geom = geom.simplify(tolerance, preserve_topology=True)
            tolerance *= 2

        coords = [(round(x, 6), round(y, 6)) for x, y in geom.exterior.coords]
        coord_str = ", ".join(f"{x} {y}" for x, y in coords)
        simplified_wkt = f"POLYGON(({coord_str}))"
        return build_skyfi_explore_url(simplified_wkt)
    except Exception:
        return build_skyfi_explore_url(aoi_wkt)


def build_skyfi_explore_url_from_bbox(bbox: list[float]) -> str:
    """Build a SkyFi tasking URL from a bounding box [west, south, east, north].

    Kept as a fallback for cases where no polygon WKT is available.
    Prefer build_skyfi_explore_url_from_wkt when a polygon WKT is available.
    """
    if len(bbox) != 4:
        raise ValueError(f"Expected [west, south, east, north], got {bbox!r}")
    west, south, east, north = bbox
    bbox_wkt = (
        f"POLYGON(({west} {south}, {east} {south}, "
        f"{east} {north}, {west} {north}, {west} {south}))"
    )
    return build_skyfi_explore_url(bbox_wkt)



def build_skyfi_order_url(order_id: str) -> str:
    """Build a browser-friendly URL to view an order on SkyFi."""
    return f"https://app.skyfi.com/orders/{order_id}"


def register(mcp: FastMCP) -> None:
    """Register preview tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_preview_url(archive_id: str, aoi_wkt: str) -> str:
        """Generate a SkyFi preview URL to view a satellite image in the browser.

        Pure URL construction — no API call or authentication required.

        Args:
            archive_id: The full SkyFi archive identifier from search results.
            aoi_wkt: The WKT POLYGON string (area of interest) used in the search.

        Returns:
            A clickable URL to preview the image on app.skyfi.com.
        """
        return build_skyfi_preview_url(archive_id, aoi_wkt)
