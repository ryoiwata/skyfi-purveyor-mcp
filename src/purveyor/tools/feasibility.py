"""Feasibility MCP tools: check_feasibility (dual-mode), get_pass_predictions.

Design Decision §8: check_feasibility does NOT block for 60 seconds.
- Create mode: quick initial poll (2-3 attempts), return pending if not ready.
- Check mode: single poll with feasibility_id, return whatever is available.
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools._helpers import get_skyfi_client

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)

_QUICK_POLL_ATTEMPTS = 3
_QUICK_POLL_INTERVAL_S = 1.0


def register(mcp: FastMCP) -> None:
    """Register feasibility tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def check_feasibility(
        ctx: McpContext,
        location: str | None = None,
        product_type: str | None = None,
        resolution: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_cloud_cover: float | None = None,
        provider: str | None = None,
        feasibility_id: str | None = None,
    ) -> Any:
        """Check tasking feasibility for a location and parameters.

        DUAL-MODE TOOL (Design Decision §8):

        Mode 1 — Create (no feasibility_id): Provide location + parameters to create a new
        feasibility check. Returns results immediately if available, or a feasibility_id with
        status="pending" if the check is still running. Call again with feasibility_id to check.

        Mode 2 — Check (feasibility_id only): Poll SkyFi for current status and return
        whatever is available (complete, partial, or still pending).

        Args:
            location: Place name or WKT polygon (required for create mode).
            product_type: Product type (DAY, SAR, etc.) — required for create mode.
            resolution: Resolution tier (HIGH, VERY HIGH, etc.) — required for create mode.
            start_date: Start of tasking window (ISO 8601).
            end_date: End of tasking window (ISO 8601).
            max_cloud_cover: Maximum acceptable cloud coverage (0-100).
            provider: Preferred provider (PLANET, UMBRA, etc.).
            feasibility_id: Existing feasibility task ID (for check mode).
        """
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        cache = lc["cache"]

        # ---- CHECK MODE: feasibility_id provided ----
        if feasibility_id:
            log.info("tool_check_feasibility_check_mode", feasibility_id=feasibility_id)
            try:
                resp = await cached_client.get_feasibility_status(feasibility_id)
            except Exception as exc:
                return ToolError(
                    code=ErrorCode.SKYFI_UNAVAILABLE,
                    message=f"Failed to poll feasibility status: {exc}",
                ).to_call_tool_result()

            return _format_feasibility_response(resp, mode="check")

        # ---- CREATE MODE: location + parameters required ----
        if not location:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    "Either 'location' (create mode) or 'feasibility_id' (check mode) is required."
                ),
            ).to_call_tool_result()
        if not product_type or not resolution or not start_date or not end_date:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    "location, product_type, resolution, start_date, and end_date "
                    "are required for create mode."
                ),
            ).to_call_tool_result()

        log.info("tool_check_feasibility_create_mode", location=location[:50])

        from datetime import datetime

        from purveyor.core.skyfi_types import FeasibilityRequest, ProductType
        from purveyor.tools.geospatial import resolve_location

        # Resolve location
        try:
            wkt, _ = await resolve_location(
                location,
                geocoding_base_url=settings.geocoding_base_url,
                cache=cache,
            )
        except ToolError as e:
            return e.to_call_tool_result()

        # Parse dates
        try:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
            end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
        except ValueError as exc:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid date format: {exc}. Use ISO 8601.",
            ).to_call_tool_result()

        # Parse product type
        try:
            pt = ProductType(product_type)
        except ValueError:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    f"Invalid product_type '{product_type}'. "
                    f"Valid values: {[e.value for e in ProductType]}"
                ),
            ).to_call_tool_result()

        request = FeasibilityRequest(
            aoi=wkt,
            product_type=pt,
            resolution=resolution,
            start_date=start_dt,
            end_date=end_dt,
            max_cloud_coverage_percent=max_cloud_cover,
            required_provider=provider,
        )

        # Create the feasibility task
        try:
            resp = await cached_client.create_feasibility_task(request)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to create feasibility task: {exc}",
            ).to_call_tool_result()

        fid = str(resp.id)

        # Quick initial poll (2-3 attempts, ~1s each)
        for attempt in range(_QUICK_POLL_ATTEMPTS):
            try:
                status_resp = await cached_client.get_feasibility_status(fid)
            except Exception:
                break

            score = status_resp.overall_score
            if score is not None:
                # Results are ready
                return _format_feasibility_response(status_resp, mode="create")

            if attempt < _QUICK_POLL_ATTEMPTS - 1:
                await asyncio.sleep(_QUICK_POLL_INTERVAL_S)

        # Still pending after quick poll
        return {
            "feasibility_id": fid,
            "status": "pending",
            "message": (
                "Feasibility check is running. Call check_feasibility again with "
                f"feasibility_id='{fid}' to retrieve results."
            ),
            "summary": (
                f"Feasibility task created (ID: {fid}). "
                "Results not yet available — check back in a few seconds."
            ),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_pass_predictions(
        location: str,
        from_date: str,
        to_date: str,
        ctx: McpContext,
        product_types: list[str] | None = None,
        resolutions: list[str] | None = None,
        max_off_nadir: float | None = None,
    ) -> Any:
        """Find satellite passes over a location within a time window.

        Returns per-satellite pass details including timing, off-nadir angle, and pricing.
        Results sorted by pass date ascending.

        Args:
            location: Place name or WKT polygon.
            from_date: Start of prediction window (ISO 8601).
            to_date: End of prediction window (ISO 8601).
            product_types: Filter by product type (DAY, SAR, etc.).
            resolutions: Filter by resolution tier.
            max_off_nadir: Maximum off-nadir angle (degrees, default 30).
        """
        log.info("tool_get_pass_predictions", location=location[:50])
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        cache = lc["cache"]

        from datetime import datetime

        from purveyor.core.skyfi_types import PassPredictionRequest, ProductType
        from purveyor.tools.geospatial import resolve_location

        # Resolve location
        try:
            wkt, _ = await resolve_location(
                location,
                geocoding_base_url=settings.geocoding_base_url,
                cache=cache,
            )
        except ToolError as e:
            return e.to_call_tool_result()

        # Parse dates
        try:
            from_dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
            to_dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
        except ValueError as exc:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid date format: {exc}. Use ISO 8601.",
            ).to_call_tool_result()

        product_types_parsed = None
        if product_types:
            try:
                product_types_parsed = [ProductType(pt) for pt in product_types]
            except ValueError as exc:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid product_type: {exc}",
                ).to_call_tool_result()

        request = PassPredictionRequest(
            aoi=wkt,
            from_date=from_dt,
            to_date=to_dt,
            product_types=product_types_parsed,
            resolutions=resolutions,
            max_off_nadir_angle=max_off_nadir,
        )

        try:
            resp = await cached_client.get_pass_predictions(request)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch pass predictions: {exc}",
            ).to_call_tool_result()

        passes = sorted(resp.passes, key=lambda p: p.pass_date)

        if not passes:
            return ToolError(
                code=ErrorCode.NO_RESULTS,
                message="No satellite passes found for the specified location and time window.",
            ).to_call_tool_result()

        # Build summary
        providers_found = sorted({str(p.provider) for p in passes})
        best = passes[0]
        prices = [p.price_for_one_square_km for p in passes]
        summary = (
            f"Found {len(passes)} satellite passes from {len(providers_found)} providers "
            f"({', '.join(providers_found)}). "
            f"Date range: {passes[0].pass_date.date()} to {passes[-1].pass_date.date()}. "
            f"Price range: ${min(prices):.4f}-${max(prices):.4f}/sq km. "
            f"Earliest pass: {best.satname} ({best.provider}) on "
            f"{best.pass_date.strftime('%Y-%m-%d %H:%M UTC')} "
            f"at {best.off_nadir_angle:.1f}° off-nadir."
        )

        return {
            "passes": [p.model_dump(mode="json") for p in passes],
            "total": len(passes),
            "summary": summary,
        }


def _format_feasibility_response(resp: Any, mode: str) -> dict[str, Any]:
    """Format a FeasibilityResponse into a tool response dict."""
    score = resp.overall_score
    fid = str(resp.id)

    if score is None:
        return {
            "feasibility_id": fid,
            "status": "pending",
            "message": "Results not yet available.",
            "summary": f"Feasibility task {fid} is still running.",
        }

    feasibility_val = score.feasibility
    weather_score = None
    if score.weather_score:
        weather_score = score.weather_score.weather_score

    provider_scores = []
    best_opportunity_text = ""
    if score.provider_score and score.provider_score.provider_scores:
        for ps in score.provider_score.provider_scores:
            provider_scores.append({
                "provider": ps.provider,
                "score": ps.score,
                "status": ps.status,
                "opportunities": len(ps.opportunities),
            })
            if ps.opportunities and not best_opportunity_text:
                opp = ps.opportunities[0]
                best_opportunity_text = (
                    f"Best opportunity: {opp.window_start.strftime('%Y-%m-%d %H:%M UTC')} "
                    f"({ps.provider})."
                )

    # Rating label
    if feasibility_val >= 0.75:
        rating = "HIGH"
    elif feasibility_val >= 0.5:
        rating = "MEDIUM"
    else:
        rating = "LOW"

    summary_parts = [f"Feasibility is {rating} ({feasibility_val:.2f})."]
    if weather_score is not None:
        summary_parts.append(f"Weather score: {weather_score:.2f}.")
    if provider_scores:
        summary_parts.append(f"{len(provider_scores)} provider(s) evaluated.")
    if best_opportunity_text:
        summary_parts.append(best_opportunity_text)

    return {
        "feasibility_id": fid,
        "status": "complete",
        "overall_score": feasibility_val,
        "weather_score": weather_score,
        "provider_scores": provider_scores,
        "valid_until": resp.valid_until.isoformat(),
        "summary": " ".join(summary_parts),
    }
