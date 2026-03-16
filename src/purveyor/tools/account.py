"""Account MCP tool: whoami."""

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
    """Register account tools on the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def whoami(
        ctx: McpContext,
    ) -> Any:
        """Get information about the authenticated SkyFi account.

        Returns user identity, budget usage, payment status, and inferred account tier.
        Cached for 5 minutes.
        """
        log.info("tool_whoami")
        cached_client = get_skyfi_client(ctx)

        try:
            user = await cached_client.whoami()
        except Exception as exc:
            log.error("whoami_error", error=str(exc))
            return ToolError(
                code=ErrorCode.SKYFI_API_ERROR,
                message=f"Failed to fetch account info: {exc}",
            ).to_call_tool_result()

        # Infer account tier (Design Decision §17)
        if user.is_demo_account:
            account_tier = "demo"
            open_data_daily_limit = 1
        elif user.budget_amount > 100_000:  # > $1000
            account_tier = "pro"
            open_data_daily_limit = 5
        else:
            account_tier = "free"
            open_data_daily_limit = 1

        budget_used_dollars = user.current_budget_usage / 100
        budget_total_dollars = user.budget_amount / 100
        budget_remaining = (user.budget_amount - user.current_budget_usage) / 100

        summary = (
            f"Logged in as {user.email} ({user.first_name} {user.last_name}). "
            f"{account_tier.capitalize()} account. "
            f"Budget: ${budget_used_dollars:.2f} of ${budget_total_dollars:.2f} used "
            f"(${budget_remaining:.2f} remaining). "
            f"Payment method: {'active' if user.has_valid_shared_card else 'not configured'}. "
            f"Open data limit: {open_data_daily_limit}/day."
        )

        return {
            "user_id": str(user.id),
            "email": user.email,
            "name": f"{user.first_name} {user.last_name}",
            "account_tier": account_tier,
            "is_demo_account": user.is_demo_account,
            "budget_used_cents": user.current_budget_usage,
            "budget_total_cents": user.budget_amount,
            "budget_remaining_cents": user.budget_amount - user.current_budget_usage,
            "has_payment_method": user.has_valid_shared_card,
            "open_data_daily_limit": open_data_daily_limit,
            "summary": summary,
        }
