"""Order management MCP tools (read-only operations for Phase 2).

Write operations (create_tasking_order, create_archive_order, cancel_pending_order)
are implemented in Phase 3.
"""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from purveyor.core.errors import ErrorCode, ToolError

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
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

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

        return {
            "orders": [o.model_dump(mode="json") for o in orders],
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
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

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

        # Collect download URLs for completed orders
        download_urls: dict[str, str | None] = {}
        if status == "DELIVERY_COMPLETED":
            download_urls = {
                "image": getattr(order, "download_image_url", None),
                "payload": getattr(order, "download_payload_url", None),
                "cog": getattr(order, "download_cog_url", None),
            }
            download_urls = {k: v for k, v in download_urls.items() if v}

        cost_str = f"${cost_cents / 100:.2f}" if cost_cents else "N/A"
        date_str = created_at.date().isoformat() if created_at else "N/A"

        summary = (
            f"{order_type} order {order_id}: status {status}. "
            f"Cost: {cost_str}. Created: {date_str}."
        )
        if download_urls:
            summary += f" {len(download_urls)} deliverable(s) available for download."

        return {
            "order": order.model_dump(mode="json"),
            "status": status,
            "download_urls": download_urls,
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
        lc: dict[str, Any] = ctx.request_context.lifespan_context
        cached_client = lc["cached_client"]

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
            "summary": (
                f"Signed download URL for {deliverable_type} of order {order_id}. "
                "URL expires - download promptly."
            ),
        }
