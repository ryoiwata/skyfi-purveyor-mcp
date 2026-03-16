"""Order management MCP tools: list, status, download, create, cancel."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.constants import SKYFI_MAX_AOI_KM2, SKYFI_MIN_AOI_KM2
from purveyor.core.errors import ErrorCode, ToolError
from purveyor.tools._helpers import get_api_key_from_ctx, get_skyfi_client
from purveyor.tools.preview import build_skyfi_order_url, build_skyfi_preview_url

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register order management tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def list_orders(
        ctx: McpContext,
        order_type: str | None = None,
        page: int = 0,
        page_size: int = 25,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ) -> Any:
        """List orders for the current account with optional filtering and sorting.

        Args:
            order_type: Filter by type — ARCHIVE or TASKING.
            page: Page number (0-indexed).
            page_size: Results per page (1-100).
            sort_by: Sort column (created_at, status, customer_item_cost).
            sort_dir: Sort direction (asc or desc).
        """
        log.info("tool_list_orders", order_type=order_type)
        cached_client = get_skyfi_client(ctx)

        from purveyor.core.skyfi_types import OrderType, SortColumn, SortDirection

        # Validate inputs
        order_type_parsed = None
        if order_type:
            try:
                order_type_parsed = OrderType(order_type.upper())
            except ValueError:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid order_type '{order_type}'. Use ARCHIVE or TASKING.",
                ).to_call_tool_result()

        sort_col = None
        if sort_by:
            try:
                sort_col = SortColumn(sort_by)
            except ValueError:
                pass  # Ignore invalid sort column, use default

        sort_direction = None
        if sort_dir:
            try:
                sort_direction = SortDirection(sort_dir.lower())
            except ValueError:
                pass

        try:
            resp = await cached_client.list_orders(
                order_type=order_type_parsed,
                page=page,
                page_size=min(max(1, page_size), 100),
                sort_columns=[sort_col] if sort_col else None,
                sort_directions=[sort_direction] if sort_direction else None,
            )
        except Exception as exc:
            log.error("list_orders_error", error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch orders: {exc}",
            ).to_call_tool_result()

        orders = resp.orders
        total = resp.total

        # Build summary
        pending = sum(
            1 for o in orders
            if hasattr(o, "status") and str(o.status) not in (
                "DELIVERY_COMPLETED", "PAYMENT_FAILED", "PLATFORM_FAILED",
                "PROVIDER_FAILED", "PROCESSING_FAILED", "DELIVERY_FAILED"
            )
        )
        delivered = sum(
            1 for o in orders
            if hasattr(o, "status") and str(o.status) == "DELIVERY_COMPLETED"
        )

        summary_parts = [f"{total} total orders."]
        if orders:
            summary_parts.append(f"{delivered} delivered, {pending} in progress.")
            latest = orders[0]
            order_type_name = str(getattr(latest, "order_type", "ORDER"))
            latest_date = getattr(latest, "created_at", None)
            if latest_date:
                summary_parts.append(
                    f"Most recent: {order_type_name} order created {latest_date.date()}."
                )

        def _order_with_web_url(o: Any) -> dict[str, Any]:
            d: dict[str, Any] = o.model_dump(mode="json")
            oid = d.get("order_id") or d.get("id") or str(getattr(o, "order_id", ""))
            # skyfi_order_url is the SkyFi web-app URL for viewing the order in a browser.
            # download_image_url (from API) is an authenticated API endpoint and must NOT
            # be given to users as a clickable link — it requires X-Skyfi-Api-Key headers.
            d["skyfi_order_url"] = build_skyfi_order_url(oid) if oid else None
            # For archive orders: add skyfi_preview_url using archive_id + order AOI.
            # If no AOI is available, omit the URL — never fall back to explore/archive links.
            archive_id = d.get("archive_id")
            order_aoi = d.get("aoi")
            if archive_id and order_aoi:
                d["skyfi_preview_url"] = build_skyfi_preview_url(str(archive_id), order_aoi)
            return d

        return {
            "orders": [_order_with_web_url(o) for o in orders],
            "total": total,
            "page": page,
            "summary": " ".join(summary_parts),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_order_status(
        order_id: str,
        ctx: McpContext,
    ) -> Any:
        """Get full status and details for a specific order.

        Returns order metadata, current status, status history, and download URLs
        for completed orders.

        Args:
            order_id: The order UUID.
        """
        log.info("tool_get_order_status", order_id=order_id)
        cached_client = get_skyfi_client(ctx)

        try:
            order = await cached_client.get_order(order_id)
        except Exception as exc:
            log.error("get_order_error", order_id=order_id, error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch order {order_id}: {exc}",
            ).to_call_tool_result()

        status = str(order.status)
        order_type = str(getattr(order, "order_type", "ORDER"))
        cost_cents = getattr(order, "order_cost", None)
        created_at = getattr(order, "created_at", None)

        # skyfi_order_url: web-app URL for viewing the order in a browser (no auth needed).
        # download_image_url from the API is an authenticated API endpoint — NOT a browser URL.
        skyfi_order_url = build_skyfi_order_url(order_id)

        # api_download_endpoints: internal API paths (require X-Skyfi-Api-Key header).
        # These are exposed for informational purposes only — agents should use
        # download_deliverable to get a time-limited signed URL for actual downloading.
        api_download_endpoints: dict[str, str | None] = {}
        if status == "DELIVERY_COMPLETED":
            api_download_endpoints = {
                "image": getattr(order, "download_image_url", None),
                "payload": getattr(order, "download_payload_url", None),
                "cog": getattr(order, "download_cog_url", None),
            }
            api_download_endpoints = {k: v for k, v in api_download_endpoints.items() if v}

        cost_str = f"${cost_cents / 100:.2f}" if cost_cents else "N/A"
        date_str = created_at.date().isoformat() if created_at else "N/A"

        summary = (
            f"{order_type} order {order_id}: status {status}. "
            f"Cost: {cost_str}. Created: {date_str}. "
            f"View order: {skyfi_order_url}"
        )
        if api_download_endpoints:
            summary += (
                f" {len(api_download_endpoints)} deliverable(s) ready."
                " Use download_deliverable to get a signed download URL."
            )

        order_dict: dict[str, Any] = order.model_dump(mode="json")
        order_dict["skyfi_order_url"] = skyfi_order_url

        # For archive orders: add skyfi_preview_url using archive_id + order AOI.
        # If no AOI is available, omit the URL — never fall back to explore/archive links.
        archive_id = order_dict.get("archive_id")
        order_aoi = order_dict.get("aoi")
        if archive_id and order_aoi:
            order_dict["skyfi_preview_url"] = build_skyfi_preview_url(
                str(archive_id), order_aoi
            )

        return {
            "order": order_dict,
            "status": status,
            "skyfi_order_url": skyfi_order_url,
            "api_download_endpoints": api_download_endpoints,
            "summary": summary,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def download_deliverable(
        order_id: str,
        deliverable_type: str,
        ctx: McpContext,
    ) -> Any:
        """Get the signed download URL for an order deliverable.

        Args:
            order_id: The order UUID.
            deliverable_type: Deliverable type — image, payload, or cog.
        """
        log.info("tool_download_deliverable", order_id=order_id, deliverable_type=deliverable_type)
        cached_client = get_skyfi_client(ctx)

        from purveyor.core.skyfi_types import DeliverableType

        try:
            dt = DeliverableType(deliverable_type.lower())
        except ValueError:
            valid = [e.value for e in DeliverableType]
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid deliverable_type '{deliverable_type}'. Valid: {valid}",
            ).to_call_tool_result()

        try:
            url = await cached_client.get_deliverable_url(order_id, dt.value)
        except Exception as exc:
            log.error("download_deliverable_error", order_id=order_id, error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to get download URL for order {order_id}: {exc}",
            ).to_call_tool_result()

        return {
            "order_id": order_id,
            "deliverable_type": deliverable_type,
            "download_url": url,
            "skyfi_order_url": build_skyfi_order_url(order_id),
            "summary": (
                f"Signed download URL for {deliverable_type} of order {order_id}. "
                "URL expires - download promptly. "
                f"View order in browser: {build_skyfi_order_url(order_id)}"
            ),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        )
    )
    async def create_tasking_order(
        location: str,
        product_type: str,
        resolution: str,
        window_start: str,
        window_end: str,
        ctx: McpContext,
        delivery_driver: str = "NONE",
        delivery_params: dict[str, Any] | None = None,
        max_cloud_cover: float | None = None,
        max_off_nadir: float | None = None,
        provider: str | None = None,
        provider_window_id: str | None = None,
        priority: bool = False,
        metadata: dict[str, Any] | None = None,
        webhook_url: str | None = None,
    ) -> Any:
        """Create a tasking order request. Returns a confirmation URL for human review.

        Does NOT place an order directly. Returns a confirmation URL that the user
        must open to review details and approve.

        Args:
            location: Place name or WKT polygon defining the area of interest.
            product_type: Imagery product type (DAY, SAR, MULTISPECTRAL, etc.).
            resolution: Resolution tier (LOW, MEDIUM, HIGH, VERY HIGH, SUPER HIGH, etc.).
            window_start: Capture window start (ISO 8601 datetime string).
            window_end: Capture window end (ISO 8601 datetime string).
            delivery_driver: Delivery destination (NONE, S3, GS, AZURE, etc.).
            delivery_params: Delivery credentials dict for the chosen driver.
            max_cloud_cover: Maximum cloud coverage percent (0-100).
            max_off_nadir: Maximum off-nadir angle in degrees.
            provider: Specific satellite provider to use.
            provider_window_id: Provider-specific window ID from pass predictions.
            priority: Whether to mark as a priority item.
            metadata: Optional metadata dict to attach to the order.
            webhook_url: URL to receive ORDER STATUS UPDATES for this specific tasking order.
                Pass this when the user asks to be notified about order progress or
                wants status updates sent to an external URL (e.g. webhook.site, Slack, etc.).
                SkyFi will POST to this URL whenever the order status changes
                (e.g. CREATED, STARTED, PROCESSING_COMPLETE, DELIVERY_COMPLETED).
                NOTE: This is different from setup_monitoring which alerts about NEW imagery
                becoming available. This webhook is only for tracking THIS order's status.
        """
        log.info("tool_create_tasking_order", location=location[:50], product_type=product_type)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        session_factory = lc["session_factory"]
        cache = lc["cache"]

        from purveyor.core.confirmation import (
            compute_token_hash,
            create_confirmation,
            encrypt_confirmation_token,
            fernet_to_url_token,
        )
        from purveyor.core.skyfi_types import (
            AzureDeliveryParams,
            DeliveryDriver,
            GCSDeliveryParams,
            PricingRequest,
            S3DeliveryParams,
            TaskingOrderRequest,
        )
        from purveyor.tools.geospatial import resolve_location

        # Validate delivery params if a driver is specified
        if delivery_driver and delivery_driver != "NONE" and delivery_params:
            try:
                if delivery_driver == "S3":
                    S3DeliveryParams.model_validate(delivery_params)
                elif delivery_driver in ("GS", "GS_SERVICE_ACCOUNT"):
                    GCSDeliveryParams.model_validate(delivery_params)
                elif delivery_driver in ("AZURE", "AZURE_SERVICE_ACCOUNT"):
                    AzureDeliveryParams.model_validate(delivery_params)
            except Exception as exc:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid delivery_params for driver {delivery_driver}: {exc}",
                ).to_call_tool_result()

        # Resolve location to WKT
        try:
            wkt, _ = await resolve_location(
                location,
                geocoding_base_url=settings.geocoding_base_url,
                cache=cache,
            )
        except ToolError as e:
            return e.to_call_tool_result()

        # Calculate AOI area
        try:
            from shapely import wkt as shapely_wkt

            polygon = await asyncio.to_thread(shapely_wkt.loads, wkt)
            from purveyor.tools.geospatial import _calculate_area_sq_km

            aoi_area_sq_km = await asyncio.to_thread(_calculate_area_sq_km, polygon)
        except Exception:
            aoi_area_sq_km = 0.0

        # Validate AOI size against SkyFi order limits before creating the token
        if aoi_area_sq_km > SKYFI_MAX_AOI_KM2:
            return ToolError(
                code=ErrorCode.AOI_TOO_LARGE,
                message=(
                    f"AOI too large ({aoi_area_sq_km:.1f} km²). SkyFi maximum for orders is "
                    f"{SKYFI_MAX_AOI_KM2:,.0f} km². Try creating a smaller AOI using "
                    "create_aoi_from_point with a smaller radius, or geocode a more specific location."  # noqa: E501
                ),
            ).to_call_tool_result()
        if 0 < aoi_area_sq_km < SKYFI_MIN_AOI_KM2:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    f"AOI too small ({aoi_area_sq_km:.1f} km²). SkyFi minimum for orders is "
                    f"{SKYFI_MIN_AOI_KM2} km². Try creating a larger AOI using "
                    "create_aoi_from_point with a bigger radius."
                ),
            ).to_call_tool_result()

        # Estimate cost via pricing API
        estimated_cost_cents = 0
        price_per_sq_km = 0.0
        try:
            pricing_resp = await cached_client.get_pricing(PricingRequest(aoi=wkt))
            if isinstance(pricing_resp, dict):
                # Attempt to extract price for the given product_type/resolution
                for _key, entry in pricing_resp.items():
                    if isinstance(entry, dict):
                        pt = entry.get("productType") or entry.get("product_type", "")
                        res = entry.get("resolution", "")
                        pt_match = str(pt).upper() == product_type.upper()
                        res_match = str(res).upper() == resolution.upper()
                        if pt_match and res_match:
                            ppm = entry.get("priceForOneSquareKmCents") or entry.get(
                                "price_for_one_square_km_cents", 0
                            )
                            price_per_sq_km = float(ppm) / 100.0
                            break
            if price_per_sq_km > 0 and aoi_area_sq_km > 0:
                estimated_cost_cents = int(price_per_sq_km * aoi_area_sq_km * 100)
        except Exception as exc:
            log.warning("pricing_estimate_failed", error=str(exc))

        # Parse window dates for the request
        from datetime import datetime

        try:
            ws = datetime.fromisoformat(window_start)
            we = datetime.fromisoformat(window_end)
        except ValueError as exc:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid window date format: {exc}",
            ).to_call_tool_result()

        # Build order request dict for the encrypted token payload
        driver_enum = DeliveryDriver.NONE
        try:
            driver_enum = DeliveryDriver(delivery_driver.upper())
        except ValueError:
            pass

        order_request = TaskingOrderRequest(
            aoi=wkt,
            window_start=ws,
            window_end=we,
            product_type=product_type,  # type: ignore[arg-type]
            resolution=resolution,
            delivery_driver=driver_enum,
            delivery_params=delivery_params,
            priority_item=priority,
            max_cloud_coverage_percent=(
                int(max_cloud_cover) if max_cloud_cover is not None else None
            ),
            max_off_nadir_angle=(
                int(max_off_nadir) if max_off_nadir is not None else None
            ),
            required_provider=provider,  # type: ignore[arg-type]
            provider_window_id=uuid.UUID(provider_window_id) if provider_window_id else None,
            metadata=metadata,
            webhook_url=webhook_url,
        )

        # Build Fernet token — only the API key is secret.
        # Order params go into the DB so the URL token stays short enough
        # for LLMs to render without truncation (~194 chars vs ~960 chars).
        api_key = get_api_key_from_ctx(ctx)
        token_payload = {"api_key": api_key}

        try:
            token = encrypt_confirmation_token(token_payload, settings.fernet_key)
        except Exception as enc_exc:
            log.error("tasking_order_token_encrypt_failed", error=str(enc_exc))
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Failed to create confirmation token: {enc_exc}",
            ).to_call_tool_result()

        # Compute api_key_hash for DB routing
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Store order params in DB (non-sensitive; API key stays encrypted in token)
        order_payload_json = json.dumps({
            "order_params": order_request.model_dump(by_alias=True, mode="json"),
            "webhook_url": webhook_url,
        })

        # Persist confirmation record
        try:
            async with session_factory() as session:
                record = await create_confirmation(
                    session, token, "TASKING", api_key_hash, estimated_cost_cents,
                    order_payload_json=order_payload_json,
                )
        except Exception as db_exc:
            log.error("tasking_order_db_write_failed", error=str(db_exc))
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Failed to save confirmation record: {db_exc}",
            ).to_call_tool_result()

        # Build confirmation URL
        base = (settings.confirmation_base_url or f"http://localhost:{settings.server_port}").rstrip("/")
        confirmation_url = f"{base}/confirm/{fernet_to_url_token(token)}"

        cost_str = f"${estimated_cost_cents / 100:.2f}"
        area_str = f"{aoi_area_sq_km:.1f} sq km" if aoi_area_sq_km else "unknown area"

        webhook_note = (
            f" Order status updates will be POSTed to: {webhook_url}"
            if webhook_url else ""
        )
        summary = (
            f"Tasking order for {product_type} / {resolution} over {area_str}. "
            f"Estimated cost: {cost_str}. "
            f"Window: {ws.date()} to {we.date()}."
            f"{webhook_note} "
            "Share the confirmation URL with the user for review and approval. "
            "Open the confirmation link in your browser to review and approve the order."
        )

        fernet_key_fingerprint = hashlib.sha256(settings.fernet_key).hexdigest()[:8]
        log.info(
            "tasking_order_confirmation_created",
            confirmation_id=str(record.id),
            estimated_cost_cents=estimated_cost_cents,
            fernet_key_fingerprint=fernet_key_fingerprint,
            token_hash_prefix=compute_token_hash(token)[:16],
            webhook_url=webhook_url,
        )

        tasking_response: dict[str, Any] = {
            "confirmation_url": confirmation_url,
            "confirmation_id": str(record.id),
            "estimated_cost_cents": estimated_cost_cents,
            "estimated_cost_dollars": cost_str,
            "aoi_area_km2": round(aoi_area_sq_km, 2),
            "order_summary": summary,
            "skyfi_orders_url": "https://app.skyfi.com/orders",
            "IMPORTANT": (
                "Please share this URL with the user and ask them to review and confirm the order."
            ),
        }
        if webhook_url:
            tasking_response["webhook_url_registered"] = webhook_url
            tasking_response["webhook_note"] = (
                "SkyFi will POST order status updates to this URL as the order progresses "
                "(CREATED → PROCESSING_COMPLETE → DELIVERY_COMPLETED)."
            )
        return tasking_response

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        )
    )
    async def create_archive_order(
        aoi: str,
        archive_id: str,
        ctx: McpContext,
        delivery_driver: str = "NONE",
        delivery_params: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        webhook_url: str | None = None,
    ) -> Any:
        """Create an archive order request. Returns a confirmation URL for human review.

        Does NOT place an order directly. Returns a confirmation URL that the user
        must open to review details and approve.

        Args:
            aoi: WKT polygon defining the area to order (subset of archive footprint).
            archive_id: The archive ID returned by search_archives.
            delivery_driver: Delivery destination (NONE, S3, GS, AZURE, etc.).
            delivery_params: Delivery credentials dict for the chosen driver.
            metadata: Optional metadata dict to attach to the order.
            webhook_url: URL to receive ORDER STATUS UPDATES for this specific order.
                Pass this when the user asks to be notified about order progress or
                wants status updates sent to an external URL (e.g. webhook.site, Slack, etc.).
                SkyFi will POST to this URL whenever the order status changes
                (e.g. CREATED, STARTED, PROCESSING_COMPLETE, DELIVERY_COMPLETED).
                NOTE: This is different from setup_monitoring which alerts about NEW imagery
                becoming available. This webhook is only for tracking THIS order's status.
        """
        log.info("tool_create_archive_order", archive_id=archive_id)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = get_skyfi_client(ctx)
        settings = lc["settings"]
        session_factory = lc["session_factory"]

        from purveyor.core.confirmation import (
            compute_token_hash,
            create_confirmation,
            encrypt_confirmation_token,
            fernet_to_url_token,
        )
        from purveyor.core.skyfi_types import (
            ArchiveOrderRequest,
            AzureDeliveryParams,
            DeliveryDriver,
            GCSDeliveryParams,
            S3DeliveryParams,
        )

        # Validate delivery params
        if delivery_driver and delivery_driver != "NONE" and delivery_params:
            try:
                if delivery_driver == "S3":
                    S3DeliveryParams.model_validate(delivery_params)
                elif delivery_driver in ("GS", "GS_SERVICE_ACCOUNT"):
                    GCSDeliveryParams.model_validate(delivery_params)
                elif delivery_driver in ("AZURE", "AZURE_SERVICE_ACCOUNT"):
                    AzureDeliveryParams.model_validate(delivery_params)
            except Exception as exc:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid delivery_params for driver {delivery_driver}: {exc}",
                ).to_call_tool_result()

        # Fetch archive metadata for pricing
        try:
            archive = await cached_client.get_archive(archive_id)
        except Exception as exc:
            log.error("get_archive_error", archive_id=archive_id, error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch archive {archive_id}: {exc}",
            ).to_call_tool_result()

        # Calculate AOI area
        aoi_area_sq_km = 0.0
        try:
            from shapely import wkt as shapely_wkt

            polygon = await asyncio.to_thread(shapely_wkt.loads, aoi)
            from purveyor.tools.geospatial import _calculate_area_sq_km

            aoi_area_sq_km = await asyncio.to_thread(_calculate_area_sq_km, polygon)
        except Exception as area_exc:
            log.warning("archive_area_calc_failed", error=str(area_exc))

        # Global order limits — fail fast before per-archive check
        if aoi_area_sq_km > SKYFI_MAX_AOI_KM2:
            return ToolError(
                code=ErrorCode.AOI_TOO_LARGE,
                message=(
                    f"AOI too large ({aoi_area_sq_km:.1f} km²). SkyFi maximum for orders is "
                    f"{SKYFI_MAX_AOI_KM2:,.0f} km². Use create_aoi_from_point with a smaller "
                    "radius — 25-100 km² is typical for most use cases."
                ),
            ).to_call_tool_result()
        if 0 < aoi_area_sq_km < SKYFI_MIN_AOI_KM2:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    f"AOI too small ({aoi_area_sq_km:.1f} km²). SkyFi minimum for orders is "
                    f"{SKYFI_MIN_AOI_KM2} km². Use create_aoi_from_point with a larger radius."
                ),
            ).to_call_tool_result()

        # Validate AOI size against THIS archive's own min/max limits (per-archive,
        # not a global constant — SkyFi reports them in the error as min <= actual <= max).
        archive_min = archive.min_sq_km
        archive_max = archive.max_sq_km
        if aoi_area_sq_km > archive_max:
            return ToolError(
                code=ErrorCode.AOI_TOO_LARGE,
                message=(
                    f"AOI too large ({aoi_area_sq_km:.1f} km²). "
                    f"This archive supports a maximum of {archive_max:.0f} km². "
                    "Try create_aoi_from_point with a smaller radius, "
                    "or geocode a more specific location."
                ),
            ).to_call_tool_result()
        if 0 < aoi_area_sq_km < archive_min:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=(
                    f"AOI too small ({aoi_area_sq_km:.1f} km²). "
                    f"This archive requires a minimum of {archive_min:.0f} km². "
                    "Try create_aoi_from_point with a bigger radius."
                ),
            ).to_call_tool_result()

        # Estimate cost from archive pricing
        price_per_sq_km_cents = getattr(archive, "price_for_one_square_km_cents", 0) or 0
        estimated_cost_cents = int(price_per_sq_km_cents * aoi_area_sq_km)

        driver_enum = DeliveryDriver.NONE
        try:
            driver_enum = DeliveryDriver(delivery_driver.upper())
        except ValueError:
            pass

        order_request = ArchiveOrderRequest(
            aoi=aoi,
            archive_id=archive_id,
            delivery_driver=driver_enum,
            delivery_params=delivery_params,
            metadata=metadata,
            webhook_url=webhook_url,
        )

        api_key = get_api_key_from_ctx(ctx)
        token_payload = {"api_key": api_key}

        try:
            token = encrypt_confirmation_token(token_payload, settings.fernet_key)
        except Exception as enc_exc:
            log.error("archive_order_token_encrypt_failed", error=str(enc_exc))
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Failed to create confirmation token: {enc_exc}",
            ).to_call_tool_result()

        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Store order params in DB (non-sensitive; API key stays encrypted in token)
        order_payload_json = json.dumps({
            "order_params": order_request.model_dump(by_alias=True, mode="json"),
            "webhook_url": webhook_url,
        })

        try:
            async with session_factory() as session:
                record = await create_confirmation(
                    session, token, "ARCHIVE", api_key_hash, estimated_cost_cents,
                    order_payload_json=order_payload_json,
                )
        except Exception as db_exc:
            log.error("archive_order_db_write_failed", error=str(db_exc))
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Failed to save confirmation record: {db_exc}",
            ).to_call_tool_result()

        base = (settings.confirmation_base_url or f"http://localhost:{settings.server_port}").rstrip("/")
        confirmation_url = f"{base}/confirm/{fernet_to_url_token(token)}"

        cost_str = f"${estimated_cost_cents / 100:.2f}"
        provider = getattr(archive, "provider", "unknown")
        resolution = getattr(archive, "resolution", "unknown")

        webhook_note = (
            f" Order status updates will be POSTed to: {webhook_url}"
            if webhook_url else ""
        )
        summary = (
            f"Archive order for {provider} / {resolution} scene. "
            f"AOI: {aoi_area_sq_km:.1f} sq km. Estimated cost: {cost_str}."
            f"{webhook_note} "
            "Share the confirmation URL with the user for review and approval. "
            "Open the confirmation link in your browser to review and approve the order."
        )

        fernet_key_fingerprint = hashlib.sha256(settings.fernet_key).hexdigest()[:8]
        log.info(
            "archive_order_confirmation_created",
            confirmation_id=str(record.id),
            estimated_cost_cents=estimated_cost_cents,
            fernet_key_fingerprint=fernet_key_fingerprint,
            token_hash_prefix=compute_token_hash(token)[:16],
            webhook_url=webhook_url,
        )

        response: dict[str, Any] = {
            "confirmation_url": confirmation_url,
            "confirmation_id": str(record.id),
            "archive_id": archive_id,
            "skyfi_preview_url": build_skyfi_preview_url(archive_id, aoi),
            "estimated_cost_cents": estimated_cost_cents,
            "estimated_cost_dollars": cost_str,
            "aoi_area_km2": round(aoi_area_sq_km, 2),
            "order_summary": summary,
            "skyfi_orders_url": "https://app.skyfi.com/orders",
            "IMPORTANT": (
                "Please share this URL with the user and ask them to review and confirm the order."
            ),
        }
        if webhook_url:
            response["webhook_url_registered"] = webhook_url
            response["webhook_note"] = (
                "SkyFi will POST order status updates to this URL as the order progresses "
                "(CREATED → PROCESSING_COMPLETE → DELIVERY_COMPLETED)."
            )
        return response

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def cancel_pending_order(
        confirmation_id: str,
        ctx: McpContext,
    ) -> Any:
        """Cancel a pending order confirmation before it is confirmed by the user.

        Only works on orders that have not yet been confirmed (status='pending').
        Once confirmed and placed with SkyFi, cancellation is not possible via this tool.

        Args:
            confirmation_id: The confirmation ID returned by create_tasking_order
                             or create_archive_order.
        """
        log.info("tool_cancel_pending_order", confirmation_id=confirmation_id)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        session_factory = lc["session_factory"]

        from purveyor.core.confirmation import cancel_confirmation

        try:
            cid = uuid.UUID(confirmation_id)
        except ValueError:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid confirmation_id format: '{confirmation_id}'. Expected a UUID.",
            ).to_call_tool_result()

        try:
            async with session_factory() as session:
                msg = await cancel_confirmation(session, cid)
        except ToolError as e:
            return e.to_call_tool_result()

        return {
            "confirmation_id": confirmation_id,
            "status": "cancelled",
            "message": msg,
            "summary": (
                f"Order confirmation {confirmation_id} has been cancelled. No charge will occur."
            ),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def request_redelivery(
        order_id: str,
        delivery_driver: str,
        delivery_params: dict[str, Any],
        ctx: McpContext,
    ) -> Any:
        """Request redelivery of a completed order to a new destination.

        Args:
            order_id: The order UUID to redeliver.
            delivery_driver: Delivery destination driver (S3, GS, AZURE, etc.).
            delivery_params: Delivery credentials dict for the chosen driver.
        """
        log.info("tool_request_redelivery", order_id=order_id, delivery_driver=delivery_driver)
        cached_client = get_skyfi_client(ctx)

        from purveyor.core.skyfi_types import (
            AzureDeliveryParams,
            DeliveryDriver,
            GCSDeliveryParams,
            OrderRedeliveryRequest,
            S3DeliveryParams,
        )

        # Validate delivery params
        try:
            if delivery_driver == "S3":
                S3DeliveryParams.model_validate(delivery_params)
            elif delivery_driver in ("GS", "GS_SERVICE_ACCOUNT"):
                GCSDeliveryParams.model_validate(delivery_params)
            elif delivery_driver in ("AZURE", "AZURE_SERVICE_ACCOUNT"):
                AzureDeliveryParams.model_validate(delivery_params)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid delivery_params for driver {delivery_driver}: {exc}",
            ).to_call_tool_result()

        try:
            driver_enum = DeliveryDriver(delivery_driver.upper())
        except ValueError:
            return ToolError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid delivery_driver '{delivery_driver}'.",
            ).to_call_tool_result()

        redelivery_request = OrderRedeliveryRequest(
            delivery_driver=driver_enum,
            delivery_params=delivery_params,
        )

        try:
            resp = await cached_client.request_redelivery(order_id, redelivery_request)
        except Exception as exc:
            log.error("request_redelivery_error", order_id=order_id, error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to request redelivery for order {order_id}: {exc}",
            ).to_call_tool_result()

        status = getattr(resp, "status", "redelivery_requested")
        return {
            "order_id": order_id,
            "redelivery_status": status,
            "skyfi_order_url": build_skyfi_order_url(order_id),
            "summary": (
                f"Redelivery requested for order {order_id} to {delivery_driver}. "
                f"Status: {status}. View order: {build_skyfi_order_url(order_id)}"
            ),
        }
