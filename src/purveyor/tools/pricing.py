"""Pricing MCP tool: get_pricing."""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools._helpers import get_skyfi_client

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register pricing tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_pricing(
        ctx: McpContext,
        aoi: str | None = None,
        product_type: str | None = None,
        resolution: str | None = None,
    ) -> Any:
        """Get the SkyFi pricing matrix for all product/resolution/provider combinations.

        Cached for 5 minutes. When an AOI is provided, includes area-based cost estimates.

        Args:
            aoi: Optional WKT polygon or place name. When provided, shows cost for that area.
            product_type: Filter to a specific product type (DAY, SAR, etc.).
            resolution: Filter to a specific resolution tier (HIGH, VERY HIGH, etc.).
        """
        log.info("tool_get_pricing", has_aoi=aoi is not None)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        cache = lc["cache"]

        from purveyor.core.skyfi_types import PricingRequest

        # Resolve AOI if provided
        aoi_wkt: str | None = None
        aoi_area_sq_km: float | None = None
        if aoi:
            import asyncio

            from purveyor.tools.geospatial import _calculate_area_sq_km, resolve_location

            try:
                aoi_wkt, _ = await resolve_location(
                    aoi,
                    geocoding_base_url=settings.geocoding_base_url,
                    cache=cache,
                )
                from shapely import wkt as shapely_wkt
                polygon = shapely_wkt.loads(aoi_wkt)
                aoi_area_sq_km = await asyncio.to_thread(_calculate_area_sq_km, polygon)
            except ToolError as e:
                return e.to_call_tool_result()
            except Exception as exc:
                log.warning("pricing_aoi_error", error=str(exc))
                # Proceed without AOI area calculation

        # Fetch pricing
        request = PricingRequest(aoi=aoi_wkt)
        try:
            pricing_data = await cached_client.get_pricing(request)
        except Exception as exc:
            log.error("get_pricing_error", error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch pricing: {exc}",
            ).to_call_tool_result()

        # pricing_data is a raw dict from the SkyFi API
        if not isinstance(pricing_data, dict):
            # Might be a Pydantic model if returned from cache
            try:
                pricing_data = dict(pricing_data)
            except Exception:
                pricing_data = {}

        # Apply filters if requested
        filtered = pricing_data
        if product_type or resolution:
            filtered = _filter_pricing(pricing_data, product_type, resolution)

        # Build summary
        summary = _build_pricing_summary(filtered, aoi_area_sq_km)

        return {
            "pricing_matrix": filtered,
            "aoi_area_sq_km": round(aoi_area_sq_km, 2) if aoi_area_sq_km else None,
            "filters_applied": {
                "product_type": product_type,
                "resolution": resolution,
            },
            "summary": summary,
        }


def _filter_pricing(
    data: dict[str, Any], product_type: str | None, resolution: str | None
) -> dict[str, Any]:
    """Filter pricing data by product type and/or resolution."""
    if not product_type and not resolution:
        return data

    # SkyFi pricing structure is opaque — filter by iterating top-level keys
    result: dict[str, Any] = {}
    for key, value in data.items():
        if product_type and product_type.upper() not in key.upper():
            continue
        if resolution and resolution.upper() not in key.upper():
            continue
        result[key] = value

    return result if result else data


def _build_pricing_summary(data: dict[str, Any], area_sq_km: float | None) -> str:
    """Build a dense agent-facing pricing summary."""
    if not data:
        return "No pricing data available."

    parts = [f"Pricing matrix contains {len(data)} entries."]

    # Try to find price ranges
    prices: list[float] = []
    for value in data.values():
        if isinstance(value, (int, float)):
            prices.append(float(value))
        elif isinstance(value, dict):
            for v in value.values():
                if isinstance(v, (int, float)):
                    prices.append(float(v))

    if prices:
        parts.append(f"Price range: ${min(prices):.4f}-${max(prices):.4f}/sq km.")

    if area_sq_km and prices:
        min_cost = min(prices) * area_sq_km
        max_cost = max(prices) * area_sq_km
        parts.append(
            f"Estimated cost for {area_sq_km:.1f} sq km area: ${min_cost:.0f}-${max_cost:.0f}."
        )

    return " ".join(parts)
