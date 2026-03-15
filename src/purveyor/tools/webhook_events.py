"""MCP tool: list_webhook_events — reads from the in-memory demo webhook store."""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register the list_webhook_events tool on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def list_webhook_events(limit: int = 10) -> Any:
        """List recently received order webhook events.

        Shows status updates for orders that included a webhook_url pointing
        to this Purveyor instance (POST /webhooks/orders). Useful for checking
        order progress without leaving the conversation.

        Events are stored in memory and cleared on server restart. Up to 100
        recent events are retained; newest events appear first.

        Args:
            limit: Maximum number of events to return (default 10, max 100).
        """
        from purveyor.core.webhook_store import order_webhook_events

        limit = max(1, min(limit, 100))
        raw_events = list(order_webhook_events)[:limit]

        events_out = []
        for e in raw_events:
            payload = e.get("payload", {})
            order_info: dict[str, Any] = {}
            if isinstance(payload, dict):
                order_info = payload.get("order_info") or payload.get("orderInfo") or {}
            order_id: str = order_info.get("id") or order_info.get("order_id") or ""
            event_block: dict[str, Any] = {}
            if isinstance(payload, dict):
                event_block = payload.get("event") or {}
            status: str = event_block.get("status", "UNKNOWN")
            order_type: str = order_info.get("order_type") or order_info.get("orderType", "")

            entry: dict[str, Any] = {
                "received_at": e.get("received_at"),
                "status": status,
                "order_id": order_id,
                "order_type": order_type,
                "message": event_block.get("message"),
                "payload": payload,
            }
            if order_id:
                entry["skyfi_order_url"] = f"https://app.skyfi.com/orders/{order_id}"
            events_out.append(entry)

        total_stored = len(order_webhook_events)

        if not events_out:
            summary = (
                "No webhook events received yet. "
                "Place an order with webhook_url set to this Purveyor instance's "
                "/webhooks/orders endpoint to start receiving status updates."
            )
        else:
            statuses = [e["status"] for e in events_out if e["status"] != "UNKNOWN"]
            latest = events_out[0]
            summary = (
                f"{total_stored} total events stored; showing {len(events_out)}. "
                f"Latest: order {latest['order_id'] or 'unknown'} — {latest['status']}. "
                f"Statuses seen: {', '.join(dict.fromkeys(statuses)) if statuses else 'none'}."
            )

        log.info("tool_list_webhook_events", total_stored=total_stored, limit=limit)

        return {
            "total_stored": total_stored,
            "showing": len(events_out),
            "events": events_out,
            "summary": summary,
        }
