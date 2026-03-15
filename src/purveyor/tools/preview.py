"""Preview URL builder for SkyFi archive images."""

from __future__ import annotations

from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def build_skyfi_preview_url(archive_id: str, aoi_wkt: str) -> str:
    """Build a SkyFi explore/crop URL for previewing an archive image in the browser."""
    encoded_aoi = quote(aoi_wkt, safe="")
    return f"https://app.skyfi.com/explore/open/crop/{archive_id}?aoi={encoded_aoi}"


def build_skyfi_explore_url(aoi_wkt: str) -> str:
    """Build a SkyFi explore URL filtered to an AOI."""
    encoded_aoi = quote(aoi_wkt, safe="")
    return f"https://app.skyfi.com/explore?aoi={encoded_aoi}"


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
