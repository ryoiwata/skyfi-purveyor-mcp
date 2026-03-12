"""Notification MCP tools: setup_monitoring, list/get/delete notifications."""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError

McpContext = Context[Any, Any, Any]

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register notification tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def setup_monitoring(
        location: str,
        ctx: McpContext,
        webhook_url: str | None = None,
        product_type: str | None = None,
        gsd_min: int | None = None,
        gsd_max: int | None = None,
    ) -> Any:
        """Set up area-of-interest monitoring to receive alerts when new imagery is available.

        Creates a SkyFi notification that triggers a webhook when new imagery matching the
        filters is captured over the specified location.

        Design Decision §20: If webhook_url is not provided, defaults to Purveyor's own
        /webhooks/archive-notification endpoint. Warns if the resolved URL is localhost.

        Args:
            location: Place name or WKT polygon to monitor.
            webhook_url: Optional webhook URL. Defaults to Purveyor's endpoint.
            product_type: Filter by product type (DAY, SAR, etc.).
            gsd_min: Minimum ground sample distance filter (meters).
            gsd_max: Maximum ground sample distance filter (meters).
        """
        log.info("tool_setup_monitoring", location=location[:50])
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]
        settings = lc["settings"]
        cache = lc["cache"]

        from purveyor.core.skyfi_types import CreateNotificationRequest, ProductType
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

        # Resolve webhook URL
        warning: str | None = None
        if webhook_url is None:
            base = settings.webhook_base_url or settings.confirmation_base_url
            if base:
                resolved_webhook_url = f"{base.rstrip('/')}/webhooks/archive-notification"
            else:
                port = settings.server_port
                resolved_webhook_url = f"http://localhost:{port}/webhooks/archive-notification"

            # Warn if localhost
            if "localhost" in resolved_webhook_url or "127.0.0.1" in resolved_webhook_url:
                warning = (
                    "Monitor created, but the webhook URL points to localhost which SkyFi "
                    "cannot reach. Notifications won't arrive until you set WEBHOOK_BASE_URL "
                    "or provide a public webhook_url."
                )
        else:
            resolved_webhook_url = webhook_url

        # Parse product type
        product_type_parsed = None
        if product_type:
            try:
                product_type_parsed = ProductType(product_type)
            except ValueError:
                return ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid product_type '{product_type}'.",
                ).to_call_tool_result()

        request = CreateNotificationRequest(
            aoi=wkt,
            webhook_url=resolved_webhook_url,
            product_type=product_type_parsed,
            gsd_min=gsd_min,
            gsd_max=gsd_max,
        )

        try:
            notification = await cached_client.create_notification(request)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to create notification: {exc}",
            ).to_call_tool_result()

        nid = str(notification.id)
        log.info("notification_created", notification_id=nid)

        result: dict[str, Any] = {
            "notification_id": nid,
            "aoi_wkt": wkt,
            "webhook_url": resolved_webhook_url,
            "product_type": product_type,
            "gsd_min": gsd_min,
            "gsd_max": gsd_max,
            "summary": (
                f"Monitoring set up (ID: {nid}). "
                "SkyFi will notify via webhook when new imagery is available over the area."
            ),
        }
        if warning:
            result["warning"] = warning
            result["summary"] += f" WARNING: {warning}"

        return result

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def list_notifications(
        ctx: McpContext,
        page: int = 0,
        page_size: int = 25,
    ) -> Any:
        """List active area monitoring notifications.

        Args:
            page: Page number (0-indexed).
            page_size: Results per page (1-100).
        """
        log.info("tool_list_notifications")
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

        try:
            resp = await cached_client.list_notifications(
                page=page,
                page_size=min(max(1, page_size), 100),
            )
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch notifications: {exc}",
            ).to_call_tool_result()

        total = resp.total
        notifications = resp.notifications

        summary = f"{total} active monitoring notifications."
        if notifications:
            product_types = sorted({str(n.product_type) for n in notifications if n.product_type})
            if product_types:
                summary += f" Product types monitored: {', '.join(product_types)}."

        return {
            "notifications": [n.model_dump(mode="json") for n in notifications],
            "total": total,
            "page": page,
            "summary": summary,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_notification_history(
        notification_id: str,
        ctx: McpContext,
    ) -> Any:
        """Get a notification monitor with its full event history.

        Args:
            notification_id: The notification UUID.
        """
        log.info("tool_get_notification_history", notification_id=notification_id)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

        try:
            notification = await cached_client.get_notification(notification_id)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to fetch notification {notification_id}: {exc}",
            ).to_call_tool_result()

        event_count = len(notification.history)
        summary = (
            f"Notification {notification_id}: {event_count} event(s) fired. "
            f"Monitoring AOI since {notification.created_at.date()}."
        )

        return {
            "notification": notification.model_dump(mode="json"),
            "event_count": event_count,
            "summary": summary,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
        )
    )
    async def delete_notification(
        notification_id: str,
        ctx: McpContext,
    ) -> Any:
        """Delete an area monitoring notification.

        This stops future notifications for the associated AOI. The action is permanent.

        Args:
            notification_id: The notification UUID to delete.
        """
        log.info("tool_delete_notification", notification_id=notification_id)
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

        try:
            resp = await cached_client.delete_notification(notification_id)
        except Exception as exc:
            return ToolError(
                code=ErrorCode.SKYFI_UNAVAILABLE,
                message=f"Failed to delete notification {notification_id}: {exc}",
            ).to_call_tool_result()

        return {
            "notification_id": notification_id,
            "status": getattr(resp, "status", "deleted"),
            "summary": f"Notification {notification_id} deleted. No further alerts will be sent.",
        }
