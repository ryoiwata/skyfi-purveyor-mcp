"""Archive search MCP tools: search_archives, get_archive_details."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools._helpers import get_skyfi_client
from purveyor.tools.geospatial import _calculate_area_sq_km
from purveyor.tools.preview import build_skyfi_preview_url


def _best_thumbnail_url(thumbnail_urls: dict[str, str] | None) -> str | None:
    """Return the URL for the largest available thumbnail, or None if unavailable."""
    if not thumbnail_urls:
        return None

    def _area(key: str) -> int:
        try:
            w, h = key.lower().split("x")
            return int(w) * int(h)
        except (ValueError, AttributeError):
            return 0

    best_key = max(thumbnail_urls.keys(), key=_area)
    return thumbnail_urls[best_key]

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register archive tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def search_archives(
        location: str,
        ctx: McpContext,
        product_type: list[str] | None = None,
        resolution: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        max_cloud_cover: float | None = None,
        max_off_nadir: float | None = None,
        open_data: bool | None = None,
        provider: list[str] | None = None,
        page_size: int = 25,
        next_page: str | None = None,
    ) -> Any:
        """Search the SkyFi archive catalog for satellite imagery.

        Accepts a place name (geocoded automatically) or a WKT POLYGON string.
        Results are cached for 1 minute. Supports pagination via next_page cursor.

        Args:
            location: Place name (e.g. "Port of LA") or WKT POLYGON string.
            product_type: Filter by product type (DAY, SAR, MULTISPECTRAL, etc.).
            resolution: Filter by resolution (LOW, HIGH, VERY HIGH, etc.).
            from_date: Start date (ISO 8601, e.g. "2024-01-01").
            to_date: End date (ISO 8601, e.g. "2024-12-31").
            max_cloud_cover: Maximum cloud coverage percent (0-100).
            max_off_nadir: Maximum off-nadir angle (0-50 degrees).
            open_data: If true, return only free open-data imagery.
            provider: Filter by provider (PLANET, UMBRA, SENTINEL2, etc.).
            page_size: Results per page (1-100, default 25).
            next_page: Pagination cursor from a previous search response.
        """
        log.info("tool_search_archives", location=location[:50])
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        cache = lc["cache"]

        from purveyor.core.skyfi_types import ApiProvider, GetArchivesRequest, ProductType
        from purveyor.tools.geospatial import resolve_location

        # Resolve location to WKT
        try:
            wkt, location_note = await resolve_location(
                location,
                geocoding_base_url=settings.geocoding_base_url,
                cache=cache,
            )
        except ToolError as e:
            return e.to_call_tool_result()

        # Handle pagination — if next_page given, use the page endpoint
        if next_page:
            try:
                response = await cached_client.search_archives_page(next_page)
            except Exception as exc:
                log.error("search_archives_page_error", error=str(exc))
                return ToolError(
                    code=ErrorCode.SKYFI_UNAVAILABLE,
                    message=f"Failed to fetch next page: {exc}",
                ).to_call_tool_result()
        else:
            # Parse dates
            from datetime import datetime
            from_dt = None
            to_dt = None
            try:
                if from_date:
                    from_dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
                if to_date:
                    to_dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
            except ValueError as exc:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid date format: {exc}. Use ISO 8601 (e.g. '2024-01-01').",
                ).to_call_tool_result()

            # Parse product_type and provider lists
            product_types_parsed = None
            if product_type:
                try:
                    product_types_parsed = [ProductType(pt) for pt in product_type]
                except ValueError as exc:
                    return ToolError(
                        code=ErrorCode.INVALID_INPUT,
                        message=f"Invalid product_type: {exc}",
                    ).to_call_tool_result()

            providers_parsed = None
            if provider:
                try:
                    providers_parsed = [ApiProvider(p) for p in provider]
                except ValueError as exc:
                    return ToolError(
                        code=ErrorCode.INVALID_INPUT,
                        message=f"Invalid provider: {exc}",
                    ).to_call_tool_result()

            request = GetArchivesRequest(
                aoi=wkt,
                from_date=from_dt,
                to_date=to_dt,
                max_cloud_coverage_percent=max_cloud_cover,
                max_off_nadir_angle=max_off_nadir,
                resolutions=resolution,
                product_types=product_types_parsed,
                providers=providers_parsed,
                open_data=open_data,
                page_size=min(max(1, page_size), 100),
            )

            try:
                response = await cached_client.search_archives(request)
            except Exception as exc:
                log.error("search_archives_error", error=str(exc))
                return ToolError(
                    code=ErrorCode.SKYFI_UNAVAILABLE,
                    message=f"SkyFi archive search failed: {exc}",
                ).to_call_tool_result()

        archives = response.archives
        if not archives and not next_page:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message=(
                "No archives found matching the search criteria. "
                "Try broadening the date range, increasing cloud cover limit, "
                "or using a different location."
            ),
            ).to_call_tool_result()

        # Calculate AOI area (best-effort — wkt is always set at this point)
        import asyncio as _asyncio

        aoi_area_km2: float | None = None
        try:
            from shapely import wkt as _shapely_wkt

            _polygon = await _asyncio.to_thread(_shapely_wkt.loads, wkt)
            aoi_area_km2 = round(
                await _asyncio.to_thread(_calculate_area_sq_km, _polygon), 2
            )
        except Exception as _area_exc:
            log.debug("search_archives_area_calc_failed", error=str(_area_exc))

        # Build summary (Design Decision §14: dense, factual, agent-facing)
        total = response.total or len(archives)
        prices = [a.price_full_scene for a in archives if a.price_full_scene > 0]
        resolutions = [a.resolution for a in archives]
        open_count = sum(1 for a in archives if a.open_data)
        providers_found = sorted({a.provider for a in archives})
        dates = [a.capture_timestamp for a in archives]

        summary_parts = [f"Found {total} archives."]
        if dates:
            summary_parts.append(
                f"Date range: {min(dates).date()} to {max(dates).date()}."
            )
        if prices:
            summary_parts.append(
                f"Price range: ${min(prices):.0f}-${max(prices):.0f}/scene."
            )
        if open_count:
            summary_parts.append(f"{open_count} are open data (free).")
        if resolutions:
            unique_res = sorted(set(resolutions))
            summary_parts.append(f"Resolutions: {', '.join(unique_res)}.")
        if providers_found:
            summary_parts.append(f"Providers: {', '.join(str(p) for p in providers_found)}.")
        if location_note:
            summary_parts.append(f"NOTE: {location_note}")

        def _archive_with_url(a: Any) -> dict[str, Any]:
            d: dict[str, Any] = a.model_dump(mode="json")
            # preview_url: interactive crop viewer with AOI overlaid (client-side URL).
            # /explore/archive/{id} is excluded — fails for Sentinel and some other providers.
            d["preview_url"] = build_skyfi_preview_url(a.archive_id, wkt)
            # thumbnail_url: SkyFi-provided image thumbnail (always works when present).
            thumb = _best_thumbnail_url(a.thumbnail_urls)
            if thumb:
                d["thumbnail_url"] = thumb
            return d

        result: dict[str, Any] = {
            "archives": [_archive_with_url(a) for a in archives],
            "total": total,
            "next_page": response.next_page,
            "aoi_area_km2": aoi_area_km2,
            "summary": " ".join(summary_parts),
        }
        if location_note:
            result["location_note"] = location_note
        return result

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_archive_details(
        archive_id: str,
        ctx: McpContext,
    ) -> Any:
        """Get full metadata for a single archive image by ID.

        Args:
            archive_id: The archive UUID from a previous search_archives call.
        """
        log.info("tool_get_archive_details", archive_id=archive_id)
        cached_client = get_skyfi_client(ctx)

        try:
            archive = await cached_client.get_archive(archive_id)
        except Exception as exc:
            log.error("get_archive_error", archive_id=archive_id, error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch archive {archive_id}: {exc}",
            ).to_call_tool_result()

        # Build archive dict and annotate with preview fields before returning.
        archive_dict: dict[str, Any] = archive.model_dump(mode="json")

        # preview_url: interactive crop viewer built from the archive's own footprint.
        # /explore/archive/{id} is NOT used — it fails for Sentinel and some providers.
        preview_url = build_skyfi_preview_url(archive_id, archive.footprint)
        archive_dict["preview_url"] = preview_url

        # thumbnail_url: SkyFi-provided image thumbnail (API-sourced, always works when set).
        thumb = _best_thumbnail_url(archive.thumbnail_urls)
        if thumb:
            archive_dict["thumbnail_url"] = thumb

        summary = (
            f"Archive {archive_id}: {archive.provider} {archive.resolution} "
            f"captured {archive.capture_timestamp.date()}. "
            f"Cloud cover: {archive.cloud_coverage_percent or 'N/A'}%. "
            f"Price: ${archive.price_full_scene:.0f}/scene. "
            f"AOI limits: {archive.min_sq_km}-{archive.max_sq_km} km². "
        )
        if thumb:
            summary += f"Image thumbnail: {thumb}. "
        summary += f"Explore viewer: {preview_url}"

        return {
            "archive": archive_dict,
            "summary": summary,
        }
