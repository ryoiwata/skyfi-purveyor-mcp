"""MCP resource implementations for SkyFi data.

Resources provide contextual data that agents can reference without tool calls.
URIs follow the skyfi:// scheme.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register SkyFi resources on the MCP server."""

    @mcp.resource("skyfi://pricing/current")
    async def pricing_current() -> str:
        """Full pricing matrix for all SkyFi product/resolution/provider combinations.

        Cached for 5 minutes. Returns JSON-encoded pricing data.
        """
        import json

        # Resources don't have direct access to lifespan context in the same way
        # as tools. We use the module-level app state here.
        # For now, return a placeholder — full implementation after server wiring.
        log.info("resource_pricing_current")
        return json.dumps({"message": "Pricing resource — call get_pricing tool for current data."})

    @mcp.resource("skyfi://orders/recent")
    async def orders_recent() -> str:
        """Last 10 orders for the current user.

        Returns JSON-encoded list of recent orders.
        """
        import json

        log.info("resource_orders_recent")
        return json.dumps(
            {"message": "Recent orders resource - call list_orders tool for current data."}
        )

    @mcp.resource("skyfi://account/info")
    async def account_info() -> str:
        """Account details and budget for the current user.

        Returns JSON-encoded account information.
        """
        import json

        log.info("resource_account_info")
        return json.dumps({"message": "Account info resource — call whoami tool for current data."})

    @mcp.resource("skyfi://providers/list")
    async def providers_list() -> str:
        """List of available satellite imagery providers on SkyFi.

        Returns a JSON array of provider names. Cached for 1 hour.
        """
        import json

        from purveyor.core.skyfi_types import ApiProvider

        providers = [{"id": p.value, "name": p.value} for p in ApiProvider]
        return json.dumps({
            "providers": providers,
            "total": len(providers),
            "summary": f"{len(providers)} providers available on SkyFi.",
        })

    @mcp.resource("skyfi://resolutions/list")
    async def resolutions_list() -> str:
        """List of supported satellite imagery resolution tiers on SkyFi.

        Returns a JSON array of resolution tiers with their API values.
        Cached for 1 hour.
        """
        import json

        from purveyor.core.skyfi_types import Resolution

        resolutions = [
            {"id": r.name, "value": r.value, "label": r.value}
            for r in Resolution
        ]
        return json.dumps({
            "resolutions": resolutions,
            "total": len(resolutions),
            "summary": f"{len(resolutions)} resolution tiers supported.",
        })
